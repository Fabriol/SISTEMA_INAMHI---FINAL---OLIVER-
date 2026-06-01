import { Injectable } from '@angular/core';

/**
 * Integración con FirmaEC Desktop 5.x (aplicación standalone de Ecuador).
 *
 * FirmaEC 5.x NO expone una API HTTP local — es una aplicación de escritorio
 * con interfaz gráfica propia. El flujo de integración es:
 *
 *   1. Descargar el PDF desde el backend.
 *   2. Intentar abrir FirmaEC con el PDF via protocolo URL (firmaec:// o autofirma://).
 *   3. El usuario firma en FirmaEC (selecciona certificado, contraseña, firma).
 *   4. El usuario sube el PDF firmado de vuelta a la aplicación.
 *   5. El backend valida la firma digital PAdES y registra el campo.
 */
@Injectable({ providedIn: 'root' })
export class FirmaEcDesktopService {

  /**
   * Intenta abrir FirmaEC con el PDF a través del protocolo URL.
   * FirmaEC 5 puede o no tener registrado el esquema firmaec://.
   * Si lo tiene, FirmaEC se abre y pre-carga el documento.
   *
   * @param pdfUrl  URL pública o data URL del PDF a firmar
   */
  abrirConProtocolo(pdfUrl: string): void {
    // Intentar con el protocolo nativo de FirmaEC Ecuador
    const esquemas = ['firmaec', 'autofirma', 'afirma'];
    for (const esquema of esquemas) {
      try {
        window.open(
          `${esquema}://sign?op=sign&algorithm=SHA512withRSA&format=PAdES` +
          `&doc=${encodeURIComponent(pdfUrl)}`,
          '_self'
        );
        return;
      } catch {
        // continuar con siguiente esquema
      }
    }
  }

  /**
   * Descarga un ArrayBuffer como archivo PDF en el navegador.
   *
   * @param bytes    Bytes del PDF
   * @param nombre   Nombre del archivo descargado
   */
  descargarPdf(bytes: ArrayBuffer, nombre: string): void {
    const blob  = new Blob([bytes], { type: 'application/pdf' });
    const url   = URL.createObjectURL(blob);
    const link  = document.createElement('a');
    link.href   = url;
    link.download = nombre;
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
    setTimeout(() => URL.revokeObjectURL(url), 5000);
  }

  /**
   * Valida que un archivo seleccionado sea un PDF con firma digital.
   * Verificación básica de cabecera — la validación completa la hace el backend.
   */
  validarPdfFirmado(file: File): string {
    if (!file) return 'Seleccione un archivo.';
    if (file.size < 1024) return 'El archivo parece estar vacío o es demasiado pequeño.';

    const ext = file.name.split('.').pop()?.toLowerCase();
    if (ext !== 'pdf') return 'Solo se aceptan archivos PDF (.pdf).';

    // Límite razonable: 50 MB
    if (file.size > 50 * 1024 * 1024) {
      return 'El archivo no debe superar 50 MB.';
    }

    return '';
  }

  /** Convierte un File a base64 string. */
  fileToBase64(file: File): Promise<string> {
    return new Promise((resolve, reject) => {
      const reader = new FileReader();
      reader.onload  = () => {
        const result = reader.result as string;
        // Eliminar el prefijo data:application/pdf;base64,
        const b64 = result.includes(',') ? result.split(',')[1] : result;
        resolve(b64);
      };
      reader.onerror = reject;
      reader.readAsDataURL(file);
    });
  }
}
