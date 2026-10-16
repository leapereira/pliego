import { Combine, Scissors, FileMinus2, FileOutput, PanelsTopLeft, Minimize2, Wrench, RotateCw, ListOrdered, Stamp, Crop, LockKeyhole, LockKeyholeOpen, PencilLine, Signature, SquareDashedMousePointer, ListChecks, Image, ScanLine, Images, Columns2, FileText, FileType2, Presentation, Sheet, Globe, Archive, ScanText, Sparkles, Languages, type LucideIcon } from 'lucide-react';

export type Category = 'all' | 'organize' | 'convert' | 'edit' | 'secure' | 'smart';
export type Tool = { id: string; title: string; description: string; category: Category; icon: LucideIcon; accept: string; multiple?: boolean; label?: string };
const pdf = '.pdf,application/pdf';
export const categories: {id: Category; label: string; short: string}[] = [
  {id:'all',label:'Todas las herramientas',short:'Todas'}, {id:'organize',label:'Organizar y optimizar',short:'Organizar'}, {id:'convert',label:'Convertir documentos',short:'Convertir'}, {id:'edit',label:'Editar y personalizar',short:'Editar'}, {id:'secure',label:'Proteger documentos',short:'Proteger'}, {id:'smart',label:'Lectura inteligente',short:'Inteligencia'}
];
export const tools: Tool[] = [
  {id:'merge',title:'Unir PDF',description:'Varios archivos, un solo documento. En el orden que tú elijas.',category:'organize',icon:Combine,accept:pdf,multiple:true},
  {id:'split',title:'Dividir PDF',description:'Separa tu documento por páginas o por intervalos.',category:'organize',icon:Scissors,accept:pdf},
  {id:'compress',title:'Comprimir PDF',description:'Reduce el peso y encuentra el tamaño adecuado.',category:'organize',icon:Minimize2,accept:pdf,label:'Popular'},
  {id:'word-to-pdf',title:'Word a PDF',description:'Conserva el formato de tus documentos de Word.',category:'convert',icon:FileType2,accept:'.doc,.docx,.odt,.rtf',multiple:true},
  {id:'pdf-to-word',title:'PDF a Word',description:'Lleva el contenido de tu PDF a un documento editable.',category:'convert',icon:FileText,accept:pdf},
  {id:'jpg-to-pdf',title:'Imagen a PDF',description:'Reúne tus fotos e imágenes en un documento.',category:'convert',icon:Image,accept:'image/jpeg,image/png,image/webp,image/tiff,image/bmp',multiple:true},
  {id:'pdf-to-jpg',title:'PDF a imagen',description:'Exporta páginas o extrae las imágenes de tu PDF.',category:'convert',icon:Images,accept:pdf},
  {id:'organize',title:'Organizar páginas',description:'Cambia el orden y construye tu propia secuencia.',category:'organize',icon:PanelsTopLeft,accept:pdf},
  {id:'remove-pages',title:'Eliminar páginas',description:'Quédate con lo que importa. Quita el resto.',category:'organize',icon:FileMinus2,accept:pdf},
  {id:'extract-pages',title:'Extraer páginas',description:'Crea un nuevo PDF con las páginas que necesitas.',category:'organize',icon:FileOutput,accept:pdf},
  {id:'rotate',title:'Girar PDF',description:'Pon cada página en la orientación correcta.',category:'edit',icon:RotateCw,accept:pdf},
  {id:'edit',title:'Editar PDF',description:'Añade textos, formas, dibujos e imágenes.',category:'edit',icon:PencilLine,accept:pdf},
  {id:'sign',title:'Firmar PDF',description:'Dibuja tu firma y colócala en el documento.',category:'edit',icon:Signature,accept:pdf},
  {id:'watermark',title:'Marca de agua',description:'Añade una nota que acompañe a cada página.',category:'edit',icon:Stamp,accept:pdf},
  {id:'page-numbers',title:'Numerar páginas',description:'Dale una referencia clara a tu documento.',category:'edit',icon:ListOrdered,accept:pdf},
  {id:'crop',title:'Recortar PDF',description:'Ajusta los márgenes y limpia los bordes.',category:'edit',icon:Crop,accept:pdf},
  {id:'protect',title:'Proteger PDF',description:'Añade una contraseña para abrir tu documento.',category:'secure',icon:LockKeyhole,accept:pdf},
  {id:'unlock',title:'Desbloquear PDF',description:'Retira la protección con la contraseña de apertura.',category:'secure',icon:LockKeyholeOpen,accept:pdf},
  {id:'redact',title:'Censurar PDF',description:'Elimina de forma permanente texto e información.',category:'secure',icon:SquareDashedMousePointer,accept:pdf},
  {id:'forms',title:'Formularios PDF',description:'Rellena campos existentes o añade nuevos.',category:'edit',icon:ListChecks,accept:pdf},
  {id:'powerpoint-to-pdf',title:'PowerPoint a PDF',description:'Convierte tus presentaciones en un PDF fácil de compartir.',category:'convert',icon:Presentation,accept:'.ppt,.pptx,.odp',multiple:true},
  {id:'excel-to-pdf',title:'Excel a PDF',description:'Transforma hojas de cálculo en páginas PDF.',category:'convert',icon:Sheet,accept:'.xls,.xlsx,.ods,.csv',multiple:true},
  {id:'pdf-to-powerpoint',title:'PDF a PowerPoint',description:'Convierte cada página en una diapositiva.',category:'convert',icon:Presentation,accept:pdf},
  {id:'pdf-to-excel',title:'PDF a Excel',description:'Extrae tablas y llévalas a una hoja de cálculo.',category:'convert',icon:Sheet,accept:pdf},
  {id:'html-to-pdf',title:'HTML a PDF',description:'Guarda una página web o código HTML como PDF.',category:'convert',icon:Globe,accept:'.html,.htm'},
  {id:'pdf-to-pdfa',title:'PDF a PDF/A',description:'Prepara documentos para su conservación a largo plazo.',category:'convert',icon:Archive,accept:pdf},
  {id:'scan-to-pdf',title:'Escanear a PDF',description:'Convierte capturas y fotografías en páginas PDF.',category:'convert',icon:ScanLine,accept:'image/*',multiple:true},
  {id:'ocr',title:'Reconocer texto',description:'Haz que los documentos escaneados se puedan buscar.',category:'smart',icon:ScanText,accept:pdf},
  {id:'compare',title:'Comparar PDF',description:'Encuentra diferencias entre dos versiones de un documento.',category:'smart',icon:Columns2,accept:pdf,multiple:true},
  {id:'pdf-to-markdown',title:'PDF a Markdown',description:'Extrae texto estructurado para seguir trabajando.',category:'convert',icon:FileText,accept:pdf},
  {id:'repair',title:'Reparar PDF',description:'Intenta recuperar archivos dañados o incompletos.',category:'organize',icon:Wrench,accept:pdf},
  {id:'summarize',title:'Resumir PDF',description:'Obtén las ideas principales con tu conexión de IA.',category:'smart',icon:Sparkles,accept:pdf,label:'IA'},
  {id:'translate',title:'Traducir PDF',description:'Traduce el contenido con tu conexión de IA.',category:'smart',icon:Languages,accept:pdf,label:'IA'}
];
export const defaultOptions = (id: string): Record<string, any> => {
 const shared = {pages:'',page:1};
 const specifics: Record<string,Record<string,any>> = {
  split:{mode:'ranges',ranges:'1-3'}, compress:{level:'balanced'}, organize:{order:''}, rotate:{angle:90},
  watermark:{text:'BORRADOR',opacity:0.2,font_size:54}, 'page-numbers':{start:1,position:'bottom-center',format:'{n}'},
  crop:{margin:24}, protect:{new_password:''}, unlock:{password:''},
  edit:{text:'',x:48,y:72,font_size:18,color:'#1e293b',annotations:[]},
  sign:{text:'',signature:'',x:80,y:650,width:170,height:70}, redact:{terms:'',rects:[]},
  forms:{values:{},fields:[],name:'campo_1',field_type:'text',x:48,y:72,width:180,height:28},
  'jpg-to-pdf':{size:'A4',margin:24,orientation:'portrait'}, 'scan-to-pdf':{size:'A4',margin:16,orientation:'portrait'},
  'pdf-to-jpg':{mode:'pages',dpi:150,quality:90}, ocr:{language:'spa'},
  'html-to-pdf':{html:'',url:''}, summarize:{length:'medium'}, translate:{target_language:'inglés'},
  'pdf-to-pdfa':{version:'2'}, 'pdf-to-word':{mode:'text'}, compare:{mode:'text'},
 };
 return {...shared,...(specifics[id]||{})};
};
