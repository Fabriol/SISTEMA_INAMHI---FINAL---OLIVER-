import Swal, { SweetAlertIcon, SweetAlertResult } from 'sweetalert2';

/**
 * Configuración visual base para todas las alertas del sistema INAMHI.
 * Usar estas funciones en lugar de Swal.fire directo para mantener consistencia.
 */

const BASE = {
  background:  '#ffffff',
  color:       '#0f172a',
  confirmButtonColor: '#2563eb',
  cancelButtonColor:  '#94a3b8',
  customClass: {
    popup:          'swal-inamhi-popup',
    title:          'swal-inamhi-title',
    htmlContainer:  'swal-inamhi-html',
    confirmButton:  'swal-inamhi-confirm',
    cancelButton:   'swal-inamhi-cancel',
    icon:           'swal-inamhi-icon',
  },
};

/** Error crítico — rojo */
export function alertaError(titulo: string, texto: string): Promise<SweetAlertResult> {
  return Swal.fire({
    ...BASE,
    icon: 'error',
    title: titulo,
    text: texto,
    confirmButtonColor: '#dc2626',
    customClass: { ...BASE.customClass, popup: 'swal-inamhi-popup swal-error' },
  });
}

/** Advertencia — naranja */
export function alertaAdvertencia(titulo: string, texto: string): Promise<SweetAlertResult> {
  return Swal.fire({
    ...BASE,
    icon: 'warning',
    title: titulo,
    text: texto,
    confirmButtonColor: '#d97706',
    customClass: { ...BASE.customClass, popup: 'swal-inamhi-popup swal-warning' },
  });
}

/** Éxito — verde */
export function alertaExito(titulo: string, texto: string): Promise<SweetAlertResult> {
  return Swal.fire({
    ...BASE,
    icon: 'success',
    title: titulo,
    text: texto,
    confirmButtonColor: '#16a34a',
    customClass: { ...BASE.customClass, popup: 'swal-inamhi-popup swal-success' },
  });
}

/** Información — azul */
export function alertaInfo(titulo: string, texto: string): Promise<SweetAlertResult> {
  return Swal.fire({
    ...BASE,
    icon: 'info',
    title: titulo,
    text: texto,
    confirmButtonColor: '#2563eb',
    customClass: { ...BASE.customClass, popup: 'swal-inamhi-popup swal-info' },
  });
}

/** Acceso denegado — rojo oscuro con icono lock */
export function alertaAccesoDenegado(texto = 'No tiene permisos para realizar esta acción.'): Promise<SweetAlertResult> {
  return Swal.fire({
    ...BASE,
    icon: 'error',
    title: '🔒 Acceso denegado',
    text: texto,
    confirmButtonColor: '#dc2626',
    confirmButtonText: 'Entendido',
    customClass: { ...BASE.customClass, popup: 'swal-inamhi-popup swal-error' },
  });
}

/** Confirmación de acción destructiva */
export function alertaConfirmar(titulo: string, texto: string, btnTexto = 'Sí, confirmar'): Promise<SweetAlertResult> {
  return Swal.fire({
    ...BASE,
    icon: 'question',
    title: titulo,
    text: texto,
    showCancelButton: true,
    confirmButtonText: btnTexto,
    cancelButtonText: 'Cancelar',
    confirmButtonColor: '#dc2626',
    customClass: { ...BASE.customClass, popup: 'swal-inamhi-popup swal-confirm' },
  });
}

/** Toast no bloqueante en la esquina superior derecha */
export function toastExito(mensaje: string): void {
  Swal.fire({
    toast: true,
    position: 'top-end',
    icon: 'success',
    title: mensaje,
    showConfirmButton: false,
    timer: 3000,
    timerProgressBar: true,
    background: '#f0fdf4',
    color: '#15803d',
    customClass: { popup: 'swal-toast-inamhi' },
  });
}

export function toastError(mensaje: string): void {
  Swal.fire({
    toast: true,
    position: 'top-end',
    icon: 'error',
    title: mensaje,
    showConfirmButton: false,
    timer: 3500,
    timerProgressBar: true,
    background: '#fef2f2',
    color: '#dc2626',
    customClass: { popup: 'swal-toast-inamhi' },
  });
}

export function toastInfo(mensaje: string): void {
  Swal.fire({
    toast: true,
    position: 'top-end',
    icon: 'info',
    title: mensaje,
    showConfirmButton: false,
    timer: 3000,
    timerProgressBar: true,
    background: '#eff6ff',
    color: '#1d4ed8',
    customClass: { popup: 'swal-toast-inamhi' },
  });
}
