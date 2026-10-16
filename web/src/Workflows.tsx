import { useEffect, useRef, useState } from 'react';
import { ArrowDown, ArrowDownToLine, ArrowRight, ArrowUp, Check, Layers3, Plus, Save, Trash2, X, Upload, FileText } from 'lucide-react';
import { defaultOptions, tools } from './catalog';
import { OptionsPanel, type Options } from './Options';
import type { Health } from './App';
import './Workflows.css';

type Step = { key: string; tool: string; options: Options };
type Template = { id: string; name: string; steps: Step[] };
const allowed = ['compress', 'rotate', 'page-numbers', 'watermark', 'crop', 'repair', 'ocr', 'protect', 'unlock', 'pdf-to-pdfa'];
const uid = () => crypto.randomUUID();
const step = (id: string): Step => ({ key: uid(), tool: id, options: defaultOptions(id) });
function storedTemplates(): Template[] { try { return JSON.parse(localStorage.getItem('pliego-workflows') || '[]'); } catch { return []; } }

export default function Workflows({ health, onClose }: { health: Health | null; onClose: () => void }) {
 const [templates, setTemplates] = useState<Template[]>(storedTemplates);
 const [name, setName] = useState('Mi flujo de documentos');
 const [steps, setSteps] = useState<Step[]>(() => [step('compress'), step('page-numbers')]);
 const [selected, setSelected] = useState(0);
 const [next, setNext] = useState('rotate');
 const [file, setFile] = useState<File | null>(null);
 const [fileDragActive, setFileDragActive] = useState(false);
 const fileInput = useRef<HTMLInputElement>(null);
 const [busy, setBusy] = useState(false);
 const [progress, setProgress] = useState(-1);
 const [error, setError] = useState('');
 const [message, setMessage] = useState('');
 const [result, setResult] = useState<{ url: string; name: string } | null>(null);
 const abort = useRef<AbortController | null>(null);
 const active = steps[selected];
 const activeTool = tools.find(t => t.id === active?.tool);
 const fileSize = (bytes: number) => bytes < 1024 * 1024 ? `${Math.max(1, Math.round(bytes / 1024))} KB` : `${(bytes / 1024 / 1024).toFixed(1)} MB`;
 const chooseFile = (chosen: File | null) => {
   if (!chosen || busy) return;
   if (chosen.type !== 'application/pdf' && !chosen.name.toLowerCase().endsWith('.pdf')) { setError('Selecciona un archivo PDF para ejecutar el flujo.'); return; }
   if (chosen.size > (health?.limits.max_file_mb || 100) * 1024 * 1024) { setError('El archivo supera el límite de tamaño.'); return; }
   setError(''); setFile(chosen); setResult(null);
 };
 useEffect(() => () => abort.current?.abort(), []);
 useEffect(() => () => { if (result) URL.revokeObjectURL(result.url); }, [result]);
 useEffect(() => { const handler = (e: KeyboardEvent) => { if (e.key === 'Escape' && !busy) onClose(); }; window.addEventListener('keydown', handler); return () => window.removeEventListener('keydown', handler); }, [busy, onClose]);
 const save = () => {
   if (!name.trim() || !steps.length) return;
   const clean = steps.map(s => { const o = { ...s.options }; delete o.password; delete o.new_password; return { ...s, options: o }; });
   const template = { id: uid(), name: name.trim(), steps: clean };
   const list = [template, ...templates].slice(0, 20);
   setTemplates(list); localStorage.setItem('pliego-workflows', JSON.stringify(list));
   setMessage('Flujo guardado. Las contraseñas se pedirán al usarlo.');
 };
 const move = (index: number, direction: number) => { const list = [...steps]; const target = index + direction; if (target < 0 || target >= list.length) return; [list[index], list[target]] = [list[target], list[index]]; setSteps(list); setSelected(target); setResult(null); };
 const run = async () => {
   setError(''); setMessage(''); setResult(null);
   if (!file) { setError('Selecciona un PDF para comenzar.'); return; }
   if (!steps.length) { setError('Añade al menos un paso.'); return; }
   const missing = steps.find(s => !health?.tools.includes(s.tool));
   if (missing) { setError(`El motor de ${tools.find(t => t.id === missing.tool)?.title} no está disponible. Revisa los ajustes.`); return; }
   if (steps.some(s => s.tool === 'protect' && !s.options.new_password)) { setError('Introduce la contraseña en el paso Proteger PDF.'); return; }
   const controller = new AbortController(); abort.current = controller;
   setBusy(true); let current = file; let currentPassword = '';
   try {
     for (let index = 0; index < steps.length; index++) {
       setProgress(index); setSelected(index);
       const s = steps[index]; const options = { ...s.options };
       if (!options.password && currentPassword) options.password = currentPassword;
       const body = new FormData(); body.append('files', current); body.append('options', JSON.stringify(options));
       const response = await fetch(`/api/process/${s.tool}`, { method: 'POST', body, signal: controller.signal });
       if (!response.ok) { const data = await response.json(); throw Error(`Paso ${index + 1}: ${typeof data.detail === 'string' ? data.detail : 'no se pudo completar la operación.'}`); }
       const blob = await response.blob();
       if (!blob.type.includes('pdf')) throw Error(`El paso ${index + 1} no devolvió un PDF.`);
       current = new File([blob], 'pliego-flujo.pdf', { type: 'application/pdf' });
       currentPassword = s.tool === 'protect' ? String(options.new_password) : s.tool === 'unlock' ? '' : String(options.password || currentPassword);
     }
     const filename = `${name.replace(/[^\p{L}\p{N} -]/gu, '').trim() || 'pliego-flujo'}.pdf`;
     setResult({ url: URL.createObjectURL(current), name: filename }); setProgress(steps.length);
   } catch (e) { setError(controller.signal.aborted ? 'La solicitud se canceló.' : e instanceof Error ? e.message : 'No se pudo completar el flujo.'); }
   finally { setBusy(false); abort.current = null; }
 };
 return <div className="modal-backdrop"><section className="modal workflow-modal" role="dialog" aria-modal="true" aria-labelledby="workflow-title">
   <div className="modal-heading"><div><span className="eyebrow">UNA VEZ. TANTAS VECES COMO QUIERAS.</span><h2 id="workflow-title">Tus flujos de trabajo</h2></div><button className="icon-button" aria-label="Cerrar flujos" onClick={onClose} disabled={busy}><X size={21}/></button></div>
   <p className="muted">Encadena herramientas y repite el proceso con otro documento. Cada paso recibe el PDF del anterior.</p>
   {templates.length > 0 && <div className="saved-workflows">{templates.map(t => <span key={t.id}><button onClick={() => { setName(t.name); setSteps(t.steps.map(s => ({ ...s, key: uid(), options: { ...defaultOptions(s.tool), ...s.options } }))); setSelected(0); setResult(null); }} disabled={busy}><Layers3 size={14}/>{t.name}</button><button aria-label={`Borrar flujo ${t.name}`} disabled={busy} onClick={() => { const list = templates.filter(v => v.id !== t.id); setTemplates(list); localStorage.setItem('pliego-workflows', JSON.stringify(list)); }}><X size={12}/></button></span>)}</div>}
   <fieldset disabled={busy} className="workflow-fields"><label className="field">Nombre del flujo<input value={name} onChange={e => setName(e.target.value)} maxLength={80}/></label>
   <div className="workflow-editor"><div className="workflow-steps">{steps.map((s, i) => { const tool = tools.find(t => t.id === s.tool)!; const Icon = tool.icon; return <div className={`workflow-step ${selected === i ? 'selected' : ''} ${progress > i ? 'done' : ''}`} key={s.key}><button className="workflow-step-select" onClick={() => setSelected(i)}><span>{progress > i ? <Check size={14}/> : i + 1}</span><Icon size={17}/><strong>{tool.title}</strong></button><div className="workflow-step-controls"><button aria-label={`Subir paso ${i + 1}`} onClick={() => move(i, -1)} disabled={i === 0}><ArrowUp size={12}/></button><button aria-label={`Bajar paso ${i + 1}`} onClick={() => move(i, 1)} disabled={i === steps.length - 1}><ArrowDown size={12}/></button><button aria-label={`Eliminar paso ${i + 1}`} onClick={() => { setSteps(steps.filter((_, n) => n !== i)); setSelected(Math.max(0, Math.min(selected, steps.length - 2))); setResult(null); }}><Trash2 size={12}/></button></div></div>; })}<div className="workflow-add"><select value={next} onChange={e => setNext(e.target.value)} aria-label="Herramienta para añadir al flujo">{allowed.map(id => <option key={id} value={id}>{tools.find(t => t.id === id)?.title}</option>)}</select><button className="secondary-button" disabled={steps.length >= 10} onClick={() => { setSteps([...steps, step(next)]); setSelected(steps.length); setResult(null); }} aria-label="Añadir paso"><Plus size={17}/></button></div><small className="muted">Hasta 10 pasos por flujo. Las contraseñas no se guardan en las plantillas.</small></div>
   <div className="workflow-options">{active && activeTool ? <><h3>{selected + 1}. {activeTool.title}</h3><OptionsPanel tool={activeTool} options={active.options} onChange={patch => { setSteps(steps.map((s, i) => i === selected ? { ...s, options: { ...s.options, ...patch } } : s)); setResult(null); }} inspect={null} mode="none" onMode={() => {}} previewPage={1}/></> : <p className="muted">Añade una herramienta para configurar el primer paso.</p>}</div></div>
   <div className="field workflow-file"><span id="workflow-file-label">Documento PDF</span>
    <input ref={fileInput} type="file" accept="application/pdf,.pdf" className="visually-hidden" tabIndex={-1} aria-labelledby="workflow-file-label" aria-describedby="workflow-file-hint" onChange={e => { chooseFile(e.target.files?.[0] || null); e.target.value = ''; }}/>
    <div className={`workflow-upload ${fileDragActive ? 'is-dragging' : ''} ${file ? 'has-file' : ''}`} onDragOver={e => { e.preventDefault(); if (!busy && e.dataTransfer.types.includes('Files')) setFileDragActive(true); }} onDragLeave={e => { if (!e.currentTarget.contains(e.relatedTarget as Node)) setFileDragActive(false); }} onDrop={e => { e.preventDefault(); setFileDragActive(false); chooseFile(e.dataTransfer.files?.[0] || null); }}>
     <span className="workflow-upload-icon" aria-hidden="true">{file ? <FileText size={24}/> : <Upload size={24}/>}</span>
     <div className="workflow-upload-info" aria-live="polite"><strong title={file?.name}>{file ? file.name : 'Un PDF, todos tus pasos'}</strong><span>{file ? `${fileSize(file.size)} · Listo para el flujo` : 'Arrastra tu documento hasta aquí'}</span><small id="workflow-file-hint">PDF · Máximo {health?.limits.max_file_mb || 100} MB por archivo</small></div>
     <button type="button" className="secondary-button workflow-upload-button" onClick={() => fileInput.current?.click()}><Plus size={16}/>{file ? 'Cambiar PDF' : 'Seleccionar PDF'}</button>
    </div>
   </div></fieldset>
   {error && <div className="error-message" role="alert">{error}</div>}{message && <p className="workflow-success" role="status"><Check size={15}/>{message}</p>}
   {busy && <div className="processing-card" role="status"><div className="processing-heading"><span className="spinner"/>Paso {progress + 1} de {steps.length}: {tools.find(t => t.id === steps[progress]?.tool)?.title}</div><div className="progress-track"><span/></div></div>}
   {result && <div className="workflow-result"><Check size={20}/><span>Todos los pasos completados</span><a className="primary-button" href={result.url} download={result.name}><ArrowDownToLine size={17}/> Descargar PDF</a></div>}
   <div className="modal-actions"><button className="secondary-button" onClick={save} disabled={busy || !steps.length}><Save size={16}/> Guardar flujo</button>{busy ? <button className="secondary-button" onClick={() => abort.current?.abort()}>Cancelar solicitud</button> : <button className="primary-button" onClick={() => void run()} disabled={!health || !steps.length}>Ejecutar flujo<ArrowRight size={17}/></button>}</div>
 </section></div>;
}
