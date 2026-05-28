import {
  Component,
  OnInit,
  OnDestroy,
  ViewChild,
  ElementRef,
  ChangeDetectionStrategy,
  ChangeDetectorRef,
} from '@angular/core';
import { CommonModule } from '@angular/common';
import {
  FormsModule,
  ReactiveFormsModule,
  FormBuilder,
  FormGroup,
  Validators,
  AbstractControl,
  ValidationErrors,
  ValidatorFn,
} from '@angular/forms';
import { RouterModule } from '@angular/router';
import { Subject, of } from 'rxjs';
import {
  catchError,
  debounceTime,
  finalize,
  takeUntil,
  timeout,
} from 'rxjs/operators';
import Swal from 'sweetalert2';
import { FormulariosService } from '../../core/services/formularios';

// ═══════════════════════════════════════════════════════════════
//  INTERFACES
// ═══════════════════════════════════════════════════════════════

export interface StepConfig {
  title: string;
  /** Lista de formControlNames planos que pertenecen a este step (para validación). */
  campos: string[];
}

export interface CampoFormulario {
  id: string;
  nombre: string;   // alias interno (igual a id, usado en puedeEditarCampo)
  etiqueta: string;
  seccion: string;
  tipo: string;
  seleccionado: boolean;
  bloqueado: boolean;
}

export interface NotificacionItem {
  id: number;
  titulo: string;
  mensaje: string;
  leido: boolean;
}

// ═══════════════════════════════════════════════════════════════
//  VALIDATORS PERSONALIZADOS
// ═══════════════════════════════════════════════════════════════

/** Valida cédula ecuatoriana de 10 dígitos con dígito verificador. */
export function cedulaEcuatorianaValidator(): ValidatorFn {
  return (control: AbstractControl): ValidationErrors | null => {
    const value = (control.value as string) ?? '';
    if (!value) return null;

    if (!/^\d{10}$/.test(value)) return { pattern: true };

    const provincia = parseInt(value.substring(0, 2), 10);
    if (provincia < 1 || provincia > 24) return { cedulaInvalida: true };

    const coef = [2, 1, 2, 1, 2, 1, 2, 1, 2];
    let suma = 0;
    for (let i = 0; i < 9; i++) {
      let v = parseInt(value[i], 10) * coef[i];
      if (v >= 10) v -= 9;
      suma += v;
    }
    const dv = suma % 10 === 0 ? 0 : 10 - (suma % 10);
    if (dv !== parseInt(value[9], 10)) return { cedulaInvalida: true };

    return null;
  };
}

/** Valida que fecha_salida sea posterior a fecha_ingreso (cross-field en el FormGroup). */
export function fechasValidator(
  startKey: string,
  endKey: string
): ValidatorFn {
  return (group: AbstractControl): ValidationErrors | null => {
    const start = group.get(startKey)?.value;
    const end = group.get(endKey)?.value;
    if (!start || !end) return null;
    return new Date(end) <= new Date(start) ? { fechasInvalidas: true } : null;
  };
}

/** Valida que una fecha no sea futura. */
export function noFuturaValidator(): ValidatorFn {
  return (control: AbstractControl): ValidationErrors | null => {
    if (!control.value) return null;
    const hoy = new Date();
    hoy.setHours(23, 59, 59, 999);
    return new Date(control.value) > hoy ? { fechaFutura: true } : null;
  };
}

/** Valida que email2 sea diferente de email1 (cross-field). */
export function emailsDiferentesValidator(): ValidatorFn {
  return (group: AbstractControl): ValidationErrors | null => {
    const e1 = group.get('email1')?.value?.toLowerCase().trim();
    const e2 = group.get('email2')?.value?.toLowerCase().trim();
    if (!e1 || !e2) return null;
    return e1 === e2 ? { emailsIguales: true } : null;
  };
}

// ═══════════════════════════════════════════════════════════════
//  COMPONENTE
// ═══════════════════════════════════════════════════════════════

@Component({
  selector: 'app-formularios',
  standalone: true,
  imports: [CommonModule, FormsModule, ReactiveFormsModule, RouterModule],
  templateUrl: './formularios.html',
  styleUrl: './formularios.scss',
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class Formularios implements OnInit, OnDestroy {

  // ── Referencia al canvas de firma ───────────────────────────
  @ViewChild('firmaCanvas') firmaCanvasRef!: ElementRef<HTMLCanvasElement>;

  private destroy$ = new Subject<void>();
  private canvasCtx: CanvasRenderingContext2D | null = null;
  private isDrawingCanvas = false;
  private alertaActiva = false;

  // ── Fecha de hoy (para max en inputs date) ──────────────────
  hoy: string = new Date().toISOString().split('T')[0];

  // ── Estado UI ───────────────────────────────────────────────
  cargando = false;
  currentStep = 0;
  asignacionSubmitted = false;
  erroresPaso: string[] = [];
  shakeErrors = false;
  /** Controla si el contenido principal está desplegado (oculto hasta que el usuario haga clic en la alerta). */
  contenidoVisible = false;

  // ── Firma servidor saliente ─────────────────────────────────
  firmaMode: 'canvas' | 'upload' = 'canvas';
  firmaImagePreview: string | null = null;
  hasFirma = false;
  firmaRequired = false;

  // ── FirmaEC por fila (responsable de cada ítem del formulario) ─
  firmasEC: Record<string, string | null> = {
    // Trámites y Unidad
    tramites_r1: null, tramites_r2: null, tramites_r3: null, tramites_jefe: null,
    // Gestión Administrativa
    admin_r1: null, admin_r2: null, admin_r3: null, admin_r4: null, admin_dir: null,
    // Gestión TIC
    tic_r1: null, tic_r2: null, tic_r3: null, tic_r4: null, tic_r5: null,
    // Gestión Financiera
    fin_r1: null, fin_r2: null, fin_r3: null, fin_r4: null, fin_dir: null,
    // Seguridad de la Información
    seg_r1: null, seg_r2: null, seg_oficial: null,
    // Recursos Humanos
    rrhh_r1: null, rrhh_r2: null, rrhh_r3: null, rrhh_r4: null,
    rrhh_r5: null, rrhh_r6: null, rrhh_r7: null, rrhh_r8: null, rrhh_dir: null,
    // Recepción
    recepcion_r1: null,
  };
  firmasECRequired: Record<string, boolean> = {
    tramites_r1: false, tramites_r2: false, tramites_r3: false, tramites_jefe: false,
    admin_r1: false, admin_r2: false, admin_r3: false, admin_r4: false, admin_dir: false,
    tic_r1: false, tic_r2: false, tic_r3: false, tic_r4: false, tic_r5: false,
    fin_r1: false, fin_r2: false, fin_r3: false, fin_r4: false, fin_dir: false,
    seg_r1: false, seg_r2: false, seg_oficial: false,
    rrhh_r1: false, rrhh_r2: false, rrhh_r3: false, rrhh_r4: false,
    rrhh_r5: false, rrhh_r6: false, rrhh_r7: false, rrhh_r8: false, rrhh_dir: false,
    recepcion_r1: false,
  };

  // ── Datos del sistema ───────────────────────────────────────
  formularios: any[] = [];
  formularioSeleccionado: any = null;
  usuariosDisponibles: any[] = [];
  notificaciones: NotificacionItem[] = [];
  usuario: any = {};
  asignacion = { usuario_id: '' };

  // ── Control de campos ───────────────────────────────────────
  /** Campos que el usuario actual puede editar (enviados por el admin). */
  camposAsignadosUsuario: string[] = [];
  /** Campos que ya tienen respuesta guardada → readonly. */
  camposBloqueados: string[] = [];
  /** Campos que ya fueron designados a alguien → checkbox bloqueado en panel admin. */
  camposYaDesignados: string[] = [];

  // ── Steps ───────────────────────────────────────────────────
  steps: StepConfig[] = [
    {
      title: 'Información Principal',
      campos: [
        'nombres_apellidos', 'modalidad', 'cedula',
        'fecha_ingreso', 'fecha_salida', 'direccion',
        'numero_domicilio', 'celular', 'emergencia',
        'email1', 'email2', 'provincia', 'canton',
        'lugar_trabajo', 'unidad', 'cargo', 'grupo_ocupacional',
      ],
    },
    {
      title: 'Gestiones',
      campos: [
        // Trámites y Unidad
        'tramites_informe', 'tramites_fe_presentacion', 'tramites_losep',
        'tramites_admin_contrato', 'tramites_desc_contrato', 'tramites_memo',
        'tramites_jefe_inmediato', 'tramites_quipux_cero',
        'tramites_claves_asignadas', 'tramites_acta_claves',
        'tramites_servidor_recibe', 'tramites_nombre_responsable',
        'tramites_nombre_resp1', 'tramites_nombre_resp2', 'tramites_nombre_resp3',
        // Gestión Administrativa
        'admin_informe', 'admin_bienes', 'admin_acta_bienes',
        'admin_valor_bienes', 'admin_deducibles', 'admin_deducibles_valor',
        'admin_pasajes', 'admin_pasajes_valor', 'admin_responsable',
        'admin_nombre_resp1', 'admin_nombre_resp2', 'admin_nombre_resp3', 'admin_nombre_resp4',
        // Gestión TIC
        'tic_verificacion', 'tic_ip_fija', 'tic_liberacion',
        'tic_retiro_acceso', 'tic_backup', 'tic_ruta_backup',
        'tic_cierre_correo', 'tic_esigef', 'tic_spryn', 'tic_esbye', 'tic_quipux',
        'tic_tarjeta_cuentas', 'tic_responsable',
        'tic_nombre_resp1', 'tic_nombre_resp2', 'tic_nombre_resp3', 'tic_nombre_resp4',
        // Gestión Financiera
        'fin_saldos', 'fin_saldos_valor', 'fin_saldos_obs',
        'fin_anticipo', 'fin_anticipo_valor', 'fin_anticipo_obs',
        'fin_recuperacion', 'fin_recuperacion_valor', 'fin_recuperacion_obs',
        'fin_devolucion', 'fin_devolucion_valor', 'fin_devolucion_obs',
        'fin_director',
        'fin_nombre_resp1', 'fin_nombre_resp2', 'fin_nombre_resp3', 'fin_nombre_resp4',
      ],
    },
    {
      title: 'RRHH, Seguridad y Firma',
      campos: [
        // Seguridad
        'seg_archivos', 'seg_archivos_fisicos', 'seg_entrega_copia',
        'seg_verificacion_info', 'seg_oficial', 'seg_responsable',
        'seg_nombre_resp1', 'seg_nombre_resp2',
        // RRHH
        'rrhh_capacitacion', 'rrhh_resp_capacitacion',
        'rrhh_evaluacion', 'rrhh_resp_evaluacion',
        'rrhh_viajes', 'rrhh_resp_viajes',
        'rrhh_siith', 'rrhh_resp_siith',
        'rrhh_resp_vacaciones', 'rrhh_resp_juramentada',
        'rrhh_resp_credencial2', 'rrhh_resp_acta',
        'rrhh_vacaciones', 'rrhh_juramentada',
        'rrhh_num_certificado', 'rrhh_num_declaracion', 'rrhh_credencial',
        'rrhh_entrega_informe_cd', 'rrhh_ropa_trabajo', 'rrhh_acta_bienes',
        'rrhh_director',
        // Recepción
        'recepcion_fecha', 'recepcion_hojas',
        'recepcion_servidor', 'recepcion_cargo',
        // Firma
        'cedula_firmante', 'fecha_firma',
      ],
    },
  ];

  // ── Secciones del acordeón (panel admin) ────────────────────
  seccionesAbiertas: Record<string, boolean> = {
    personales: true,
    direccion: false,
    tramites: false,
    admin: false,
    tic: false,
    financiero: false,
    seguridad: false,
    rrhh: false,
    recepcion: false,
    firma: false,
    firmasEC: false,
  };

  // ── Catálogo de campos para designación (admin) ─────────────
  camposFormulario: CampoFormulario[] = [
    // ── Datos Personales ──
    { id: 'nombres_apellidos', nombre: 'nombres_apellidos', etiqueta: 'Nombres y Apellidos', seccion: 'Datos Personales', tipo: 'TEXTO', seleccionado: false, bloqueado: false },
    { id: 'modalidad', nombre: 'modalidad', etiqueta: 'Modalidad Laboral', seccion: 'Datos Personales', tipo: 'SELECT', seleccionado: false, bloqueado: false },
    { id: 'cedula', nombre: 'cedula', etiqueta: 'Cédula / Pasaporte', seccion: 'Datos Personales', tipo: 'TEXTO', seleccionado: false, bloqueado: false },
    { id: 'fecha_ingreso', nombre: 'fecha_ingreso', etiqueta: 'Fecha de Ingreso', seccion: 'Datos Personales', tipo: 'FECHA', seleccionado: false, bloqueado: false },
    { id: 'fecha_salida', nombre: 'fecha_salida', etiqueta: 'Fecha de Salida', seccion: 'Datos Personales', tipo: 'FECHA', seleccionado: false, bloqueado: false },
    { id: 'direccion', nombre: 'direccion', etiqueta: 'Dirección Domiciliaria', seccion: 'Datos Personales', tipo: 'TEXTO', seleccionado: false, bloqueado: false },
    { id: 'numero_domicilio', nombre: 'numero_domicilio', etiqueta: 'Número Domicilio', seccion: 'Datos Personales', tipo: 'TEXTO', seleccionado: false, bloqueado: false },
    { id: 'celular', nombre: 'celular', etiqueta: 'Número Celular', seccion: 'Datos Personales', tipo: 'TEXTO', seleccionado: false, bloqueado: false },
    { id: 'emergencia', nombre: 'emergencia', etiqueta: 'Contacto Emergencia', seccion: 'Datos Personales', tipo: 'TEXTO', seleccionado: false, bloqueado: false },
    { id: 'email1', nombre: 'email1', etiqueta: 'Email Principal', seccion: 'Datos Personales', tipo: 'TEXTO', seleccionado: false, bloqueado: false },
    { id: 'email2', nombre: 'email2', etiqueta: 'Email Secundario', seccion: 'Datos Personales', tipo: 'TEXTO', seleccionado: false, bloqueado: false },
    { id: 'provincia', nombre: 'provincia', etiqueta: 'Provincia', seccion: 'Datos Personales', tipo: 'TEXTO', seleccionado: false, bloqueado: false },
    { id: 'canton', nombre: 'canton', etiqueta: 'Cantón', seccion: 'Datos Personales', tipo: 'TEXTO', seleccionado: false, bloqueado: false },
    // ── Dirección / Unidad ──
    { id: 'lugar_trabajo', nombre: 'lugar_trabajo', etiqueta: 'Lugar de Trabajo', seccion: 'Dirección / Unidad', tipo: 'SELECT', seleccionado: false, bloqueado: false },
    { id: 'unidad', nombre: 'unidad', etiqueta: 'Dirección / Unidad', seccion: 'Dirección / Unidad', tipo: 'TEXTO', seleccionado: false, bloqueado: false },
    { id: 'cargo', nombre: 'cargo', etiqueta: 'Cargo Desempeñado', seccion: 'Dirección / Unidad', tipo: 'TEXTO', seleccionado: false, bloqueado: false },
    { id: 'grupo_ocupacional', nombre: 'grupo_ocupacional', etiqueta: 'Grupo Ocupacional', seccion: 'Dirección / Unidad', tipo: 'SELECT', seleccionado: false, bloqueado: false },
    // ── Trámites y Unidad ──
    { id: 'tramites_informe', nombre: 'tramites_informe', etiqueta: 'Entrega informe fin de gestión', seccion: 'Trámites y Unidad', tipo: 'SELECT', seleccionado: false, bloqueado: false },
    { id: 'tramites_fe_presentacion', nombre: 'tramites_fe_presentacion', etiqueta: 'Fe de presentación entrega recepción', seccion: 'Trámites y Unidad', tipo: 'SELECT', seleccionado: false, bloqueado: false },
    { id: 'tramites_losep', nombre: 'tramites_losep', etiqueta: 'Entrega archivo físico y digital (LOSEP)', seccion: 'Trámites y Unidad', tipo: 'SELECT', seleccionado: false, bloqueado: false },
    { id: 'tramites_admin_contrato', nombre: 'tramites_admin_contrato', etiqueta: '¿Es Administrador de Contrato?', seccion: 'Trámites y Unidad', tipo: 'SELECT', seleccionado: false, bloqueado: false },
    { id: 'tramites_desc_contrato', nombre: 'tramites_desc_contrato', etiqueta: 'Descripción del contrato', seccion: 'Trámites y Unidad', tipo: 'TEXTO', seleccionado: false, bloqueado: false },
    { id: 'tramites_memo', nombre: 'tramites_memo', etiqueta: 'Número Memorando', seccion: 'Trámites y Unidad', tipo: 'TEXTO', seleccionado: false, bloqueado: false },
    { id: 'tramites_jefe_inmediato', nombre: 'tramites_jefe_inmediato', etiqueta: 'Nombre del Jefe Inmediato', seccion: 'Trámites y Unidad', tipo: 'TEXTO', seleccionado: false, bloqueado: false },
    { id: 'tramites_quipux_cero', nombre: 'tramites_quipux_cero', etiqueta: 'QUIPUX Bandeja en Cero', seccion: 'Trámites y Unidad', tipo: 'SELECT', seleccionado: false, bloqueado: false },
    { id: 'tramites_claves_asignadas', nombre: 'tramites_claves_asignadas', etiqueta: 'Claves de acceso asignadas', seccion: 'Trámites y Unidad', tipo: 'SELECT', seleccionado: false, bloqueado: false },
    { id: 'tramites_acta_claves', nombre: 'tramites_acta_claves', etiqueta: 'Acta entrega de claves', seccion: 'Trámites y Unidad', tipo: 'SELECT', seleccionado: false, bloqueado: false },
    { id: 'tramites_servidor_recibe', nombre: 'tramites_servidor_recibe', etiqueta: 'Servidor que recibe trámites', seccion: 'Trámites y Unidad', tipo: 'TEXTO', seleccionado: false, bloqueado: false },
    { id: 'tramites_nombre_responsable', nombre: 'tramites_nombre_responsable', etiqueta: 'Nombre Responsable Trámites', seccion: 'Trámites y Unidad', tipo: 'TEXTO', seleccionado: false, bloqueado: false },
    { id: 'tramites_nombre_resp1', nombre: 'tramites_nombre_resp1', etiqueta: 'Nombre Responsable Trámites Fila 1', seccion: 'Trámites y Unidad', tipo: 'TEXTO', seleccionado: false, bloqueado: false },
    { id: 'tramites_nombre_resp2', nombre: 'tramites_nombre_resp2', etiqueta: 'Nombre Responsable Trámites Fila 2', seccion: 'Trámites y Unidad', tipo: 'TEXTO', seleccionado: false, bloqueado: false },
    { id: 'tramites_nombre_resp3', nombre: 'tramites_nombre_resp3', etiqueta: 'Nombre Responsable Trámites Fila 3', seccion: 'Trámites y Unidad', tipo: 'TEXTO', seleccionado: false, bloqueado: false },
    // ── Gestión Administrativa ──
    { id: 'admin_informe', nombre: 'admin_informe', etiqueta: '¿Realizó entrega de informe?', seccion: 'Gestión Administrativa', tipo: 'SELECT', seleccionado: false, bloqueado: false },
    { id: 'admin_bienes', nombre: 'admin_bienes', etiqueta: '¿Entregó bienes y muebles?', seccion: 'Gestión Administrativa', tipo: 'SELECT', seleccionado: false, bloqueado: false },
    { id: 'admin_acta_bienes', nombre: 'admin_acta_bienes', etiqueta: 'Número de Acta', seccion: 'Gestión Administrativa', tipo: 'TEXTO', seleccionado: false, bloqueado: false },
    { id: 'admin_valor_bienes', nombre: 'admin_valor_bienes', etiqueta: 'Valor a Descontar (Bienes)', seccion: 'Gestión Administrativa', tipo: 'NUMERO', seleccionado: false, bloqueado: false },
    { id: 'admin_deducibles', nombre: 'admin_deducibles', etiqueta: '¿Tiene Deducibles?', seccion: 'Gestión Administrativa', tipo: 'SELECT', seleccionado: false, bloqueado: false },
    { id: 'admin_deducibles_valor', nombre: 'admin_deducibles_valor', etiqueta: 'Valor Deducibles', seccion: 'Gestión Administrativa', tipo: 'NUMERO', seleccionado: false, bloqueado: false },
    { id: 'admin_pasajes', nombre: 'admin_pasajes', etiqueta: '¿Pasajes aéreos por justificar?', seccion: 'Gestión Administrativa', tipo: 'SELECT', seleccionado: false, bloqueado: false },
    { id: 'admin_pasajes_valor', nombre: 'admin_pasajes_valor', etiqueta: 'Valor a Descontar (Pasajes)', seccion: 'Gestión Administrativa', tipo: 'NUMERO', seleccionado: false, bloqueado: false },
    { id: 'admin_responsable', nombre: 'admin_responsable', etiqueta: 'Responsable Administrativo', seccion: 'Gestión Administrativa', tipo: 'TEXTO', seleccionado: false, bloqueado: false },
    { id: 'admin_nombre_resp1', nombre: 'admin_nombre_resp1', etiqueta: 'Nombre Responsable Admin Fila 1', seccion: 'Gestión Administrativa', tipo: 'TEXTO', seleccionado: false, bloqueado: false },
    { id: 'admin_nombre_resp2', nombre: 'admin_nombre_resp2', etiqueta: 'Nombre Responsable Admin Fila 2', seccion: 'Gestión Administrativa', tipo: 'TEXTO', seleccionado: false, bloqueado: false },
    { id: 'admin_nombre_resp3', nombre: 'admin_nombre_resp3', etiqueta: 'Nombre Responsable Admin Fila 3', seccion: 'Gestión Administrativa', tipo: 'TEXTO', seleccionado: false, bloqueado: false },
    { id: 'admin_nombre_resp4', nombre: 'admin_nombre_resp4', etiqueta: 'Nombre Responsable Admin Fila 4', seccion: 'Gestión Administrativa', tipo: 'TEXTO', seleccionado: false, bloqueado: false },
    // ── Gestión TIC ──
    { id: 'tic_verificacion', nombre: 'tic_verificacion', etiqueta: 'Verificación Equipo Informático', seccion: 'Gestión TIC', tipo: 'SELECT', seleccionado: false, bloqueado: false },
    { id: 'tic_ip_fija', nombre: 'tic_ip_fija', etiqueta: 'Acceso IP Fija / Wi-Fi / Móvil', seccion: 'Gestión TIC', tipo: 'SELECT', seleccionado: false, bloqueado: false },
    { id: 'tic_liberacion', nombre: 'tic_liberacion', etiqueta: 'Se realizó la liberación de IP', seccion: 'Gestión TIC', tipo: 'SELECT', seleccionado: false, bloqueado: false },
    { id: 'tic_retiro_acceso', nombre: 'tic_retiro_acceso', etiqueta: 'Retiro control acceso / contraseñas', seccion: 'Gestión TIC', tipo: 'SELECT', seleccionado: false, bloqueado: false },
    { id: 'tic_backup', nombre: 'tic_backup', etiqueta: 'Entrega Backup', seccion: 'Gestión TIC', tipo: 'SELECT', seleccionado: false, bloqueado: false },
    { id: 'tic_ruta_backup', nombre: 'tic_ruta_backup', etiqueta: 'Ruta del Backup', seccion: 'Gestión TIC', tipo: 'TEXTO', seleccionado: false, bloqueado: false },
    { id: 'tic_cierre_correo', nombre: 'tic_cierre_correo', etiqueta: 'Cierre Correo Institucional', seccion: 'Gestión TIC', tipo: 'SELECT', seleccionado: false, bloqueado: false },
    { id: 'tic_esigef', nombre: 'tic_esigef', etiqueta: 'Cierre eSIGEF', seccion: 'Gestión TIC', tipo: 'SELECT', seleccionado: false, bloqueado: false },
    { id: 'tic_spryn', nombre: 'tic_spryn', etiqueta: 'Cierre SPRYN', seccion: 'Gestión TIC', tipo: 'SELECT', seleccionado: false, bloqueado: false },
    { id: 'tic_esbye', nombre: 'tic_esbye', etiqueta: 'Cierre eSByE', seccion: 'Gestión TIC', tipo: 'SELECT', seleccionado: false, bloqueado: false },
    { id: 'tic_quipux', nombre: 'tic_quipux', etiqueta: 'Cierre QUIPUX', seccion: 'Gestión TIC', tipo: 'SELECT', seleccionado: false, bloqueado: false },
    { id: 'tic_tarjeta_cuentas', nombre: 'tic_tarjeta_cuentas', etiqueta: 'Entrega y Desactivación Tarjeta Acceso', seccion: 'Gestión TIC', tipo: 'SELECT', seleccionado: false, bloqueado: false },
    { id: 'tic_responsable', nombre: 'tic_responsable', etiqueta: 'Nombre Responsable TIC', seccion: 'Gestión TIC', tipo: 'TEXTO', seleccionado: false, bloqueado: false },
    { id: 'tic_nombre_resp1', nombre: 'tic_nombre_resp1', etiqueta: 'Nombre Responsable TIC Fila 1', seccion: 'Gestión TIC', tipo: 'TEXTO', seleccionado: false, bloqueado: false },
    { id: 'tic_nombre_resp2', nombre: 'tic_nombre_resp2', etiqueta: 'Nombre Responsable TIC Fila 2', seccion: 'Gestión TIC', tipo: 'TEXTO', seleccionado: false, bloqueado: false },
    { id: 'tic_nombre_resp3', nombre: 'tic_nombre_resp3', etiqueta: 'Nombre Responsable TIC Fila 3', seccion: 'Gestión TIC', tipo: 'TEXTO', seleccionado: false, bloqueado: false },
    { id: 'tic_nombre_resp4', nombre: 'tic_nombre_resp4', etiqueta: 'Nombre Responsable TIC Fila 4', seccion: 'Gestión TIC', tipo: 'TEXTO', seleccionado: false, bloqueado: false },
    // ── Gestión Financiera ──
    { id: 'fin_saldos', nombre: 'fin_saldos', etiqueta: 'Saldos Contables Pendientes', seccion: 'Gestión Financiera', tipo: 'SELECT', seleccionado: false, bloqueado: false },
    { id: 'fin_saldos_valor', nombre: 'fin_saldos_valor', etiqueta: 'Valor Saldos Contables', seccion: 'Gestión Financiera', tipo: 'NUMERO', seleccionado: false, bloqueado: false },
    { id: 'fin_saldos_obs', nombre: 'fin_saldos_obs', etiqueta: 'Observación Saldos', seccion: 'Gestión Financiera', tipo: 'TEXTO', seleccionado: false, bloqueado: false },
    { id: 'fin_anticipo', nombre: 'fin_anticipo', etiqueta: 'Anticipo de Sueldos Pendiente', seccion: 'Gestión Financiera', tipo: 'SELECT', seleccionado: false, bloqueado: false },
    { id: 'fin_anticipo_valor', nombre: 'fin_anticipo_valor', etiqueta: 'Valor Anticipo Sueldos', seccion: 'Gestión Financiera', tipo: 'NUMERO', seleccionado: false, bloqueado: false },
    { id: 'fin_anticipo_obs', nombre: 'fin_anticipo_obs', etiqueta: 'Observación Anticipo', seccion: 'Gestión Financiera', tipo: 'TEXTO', seleccionado: false, bloqueado: false },
    { id: 'fin_recuperacion', nombre: 'fin_recuperacion', etiqueta: 'Recuperación de Valores Pendiente', seccion: 'Gestión Financiera', tipo: 'SELECT', seleccionado: false, bloqueado: false },
    { id: 'fin_recuperacion_valor', nombre: 'fin_recuperacion_valor', etiqueta: 'Valor Recuperación', seccion: 'Gestión Financiera', tipo: 'NUMERO', seleccionado: false, bloqueado: false },
    { id: 'fin_recuperacion_obs', nombre: 'fin_recuperacion_obs', etiqueta: 'Observación Recuperación', seccion: 'Gestión Financiera', tipo: 'TEXTO', seleccionado: false, bloqueado: false },
    { id: 'fin_devolucion', nombre: 'fin_devolucion', etiqueta: 'Devolución Muebles / Equipos', seccion: 'Gestión Financiera', tipo: 'SELECT', seleccionado: false, bloqueado: false },
    { id: 'fin_devolucion_valor', nombre: 'fin_devolucion_valor', etiqueta: 'Valor Devolución Muebles', seccion: 'Gestión Financiera', tipo: 'NUMERO', seleccionado: false, bloqueado: false },
    { id: 'fin_devolucion_obs', nombre: 'fin_devolucion_obs', etiqueta: 'Observación Devolución', seccion: 'Gestión Financiera', tipo: 'TEXTO', seleccionado: false, bloqueado: false },
    { id: 'fin_director', nombre: 'fin_director', etiqueta: 'Director/a Administrativo/a Financiero/a', seccion: 'Gestión Financiera', tipo: 'TEXTO', seleccionado: false, bloqueado: false },
    { id: 'fin_nombre_resp1', nombre: 'fin_nombre_resp1', etiqueta: 'Nombre Responsable Financiero Fila 1', seccion: 'Gestión Financiera', tipo: 'TEXTO', seleccionado: false, bloqueado: false },
    { id: 'fin_nombre_resp2', nombre: 'fin_nombre_resp2', etiqueta: 'Nombre Responsable Financiero Fila 2', seccion: 'Gestión Financiera', tipo: 'TEXTO', seleccionado: false, bloqueado: false },
    { id: 'fin_nombre_resp3', nombre: 'fin_nombre_resp3', etiqueta: 'Nombre Responsable Financiero Fila 3', seccion: 'Gestión Financiera', tipo: 'TEXTO', seleccionado: false, bloqueado: false },
    { id: 'fin_nombre_resp4', nombre: 'fin_nombre_resp4', etiqueta: 'Nombre Responsable Financiero Fila 4', seccion: 'Gestión Financiera', tipo: 'TEXTO', seleccionado: false, bloqueado: false },
    // ── Seguridad ──
    { id: 'seg_archivos', nombre: 'seg_archivos', etiqueta: 'Archivos Digitales (EGSI)', seccion: 'Seguridad', tipo: 'SELECT', seleccionado: false, bloqueado: false },
    { id: 'seg_archivos_fisicos', nombre: 'seg_archivos_fisicos', etiqueta: 'Archivos Físicos (EGSI)', seccion: 'Seguridad', tipo: 'SELECT', seleccionado: false, bloqueado: false },
    { id: 'seg_entrega_copia', nombre: 'seg_entrega_copia', etiqueta: 'Entrega Copia de Informe de Actividades', seccion: 'Seguridad', tipo: 'SELECT', seleccionado: false, bloqueado: false },
    { id: 'seg_verificacion_info', nombre: 'seg_verificacion_info', etiqueta: 'Verificación de Información Institucional', seccion: 'Seguridad', tipo: 'SELECT', seleccionado: false, bloqueado: false },
    { id: 'seg_oficial', nombre: 'seg_oficial', etiqueta: 'Oficial de Seguridad Institucional', seccion: 'Seguridad', tipo: 'TEXTO', seleccionado: false, bloqueado: false },
    { id: 'seg_responsable', nombre: 'seg_responsable', etiqueta: 'Nombre Responsable Seguridad', seccion: 'Seguridad', tipo: 'TEXTO', seleccionado: false, bloqueado: false },
    { id: 'seg_nombre_resp1', nombre: 'seg_nombre_resp1', etiqueta: 'Nombre Responsable Seguridad Fila 1', seccion: 'Seguridad', tipo: 'TEXTO', seleccionado: false, bloqueado: false },
    { id: 'seg_nombre_resp2', nombre: 'seg_nombre_resp2', etiqueta: 'Nombre Responsable Seguridad Fila 2', seccion: 'Seguridad', tipo: 'TEXTO', seleccionado: false, bloqueado: false },
    // ── Recursos Humanos ──
    { id: 'rrhh_capacitacion', nombre: 'rrhh_capacitacion', etiqueta: 'Certifica: Devengó Cursos Recibidos', seccion: 'Recursos Humanos', tipo: 'SELECT', seleccionado: false, bloqueado: false },
    { id: 'rrhh_resp_capacitacion', nombre: 'rrhh_resp_capacitacion', etiqueta: 'Nombre Responsable Capacitación', seccion: 'Recursos Humanos', tipo: 'TEXTO', seleccionado: false, bloqueado: false },
    { id: 'rrhh_evaluacion', nombre: 'rrhh_evaluacion', etiqueta: 'Certifica: Evaluación del Desempeño aplicada', seccion: 'Recursos Humanos', tipo: 'SELECT', seleccionado: false, bloqueado: false },
    { id: 'rrhh_resp_evaluacion', nombre: 'rrhh_resp_evaluacion', etiqueta: 'Nombre Responsable Evaluación', seccion: 'Recursos Humanos', tipo: 'TEXTO', seleccionado: false, bloqueado: false },
    { id: 'rrhh_viajes', nombre: 'rrhh_viajes', etiqueta: 'Certifica: Devengación Viajes al Exterior', seccion: 'Recursos Humanos', tipo: 'SELECT', seleccionado: false, bloqueado: false },
    { id: 'rrhh_resp_viajes', nombre: 'rrhh_resp_viajes', etiqueta: 'Nombre Responsable Viajes al Exterior', seccion: 'Recursos Humanos', tipo: 'TEXTO', seleccionado: false, bloqueado: false },
    { id: 'rrhh_siith', nombre: 'rrhh_siith', etiqueta: 'Certifica: Desvinculación SIITH', seccion: 'Recursos Humanos', tipo: 'SELECT', seleccionado: false, bloqueado: false },
    { id: 'rrhh_resp_siith', nombre: 'rrhh_resp_siith', etiqueta: 'Nombre Responsable SIITH', seccion: 'Recursos Humanos', tipo: 'TEXTO', seleccionado: false, bloqueado: false },
    { id: 'rrhh_cursos_eval', nombre: 'rrhh_cursos_eval', etiqueta: 'Devengó Cursos / Evaluación', seccion: 'Recursos Humanos', tipo: 'SELECT', seleccionado: false, bloqueado: false },
    { id: 'rrhh_vacaciones', nombre: 'rrhh_vacaciones', etiqueta: 'Días Vacaciones Acumuladas', seccion: 'Recursos Humanos', tipo: 'NUMERO', seleccionado: false, bloqueado: false },
    { id: 'rrhh_juramentada', nombre: 'rrhh_juramentada', etiqueta: 'Entrega Constancia y Declaración Jurada', seccion: 'Recursos Humanos', tipo: 'SELECT', seleccionado: false, bloqueado: false },
    { id: 'rrhh_num_certificado', nombre: 'rrhh_num_certificado', etiqueta: 'N° Certificado Emitido', seccion: 'Recursos Humanos', tipo: 'TEXTO', seleccionado: false, bloqueado: false },
    { id: 'rrhh_num_declaracion', nombre: 'rrhh_num_declaracion', etiqueta: 'N° Declaración Juramentada', seccion: 'Recursos Humanos', tipo: 'TEXTO', seleccionado: false, bloqueado: false },
    { id: 'rrhh_credencial', nombre: 'rrhh_credencial', etiqueta: 'Entrega Credencial / Porta Credencial / Colgante', seccion: 'Recursos Humanos', tipo: 'SELECT', seleccionado: false, bloqueado: false },
    { id: 'rrhh_entrega_informe_cd', nombre: 'rrhh_entrega_informe_cd', etiqueta: 'Entrega Copia Actividades y Respaldos (CD)', seccion: 'Recursos Humanos', tipo: 'SELECT', seleccionado: false, bloqueado: false },
    { id: 'rrhh_ropa_trabajo', nombre: 'rrhh_ropa_trabajo', etiqueta: 'Entrega Ropa de Trabajo / Equipo de Protección', seccion: 'Recursos Humanos', tipo: 'SELECT', seleccionado: false, bloqueado: false },
    { id: 'rrhh_acta_bienes', nombre: 'rrhh_acta_bienes', etiqueta: 'Acta de Bienes del Custodio', seccion: 'Recursos Humanos', tipo: 'SELECT', seleccionado: false, bloqueado: false },
    { id: 'rrhh_director', nombre: 'rrhh_director', etiqueta: 'Director/a de Administración RRHH', seccion: 'Recursos Humanos', tipo: 'TEXTO', seleccionado: false, bloqueado: false },
    { id: 'rrhh_resp_vacaciones', nombre: 'rrhh_resp_vacaciones', etiqueta: 'Nombre Responsable Vacaciones RRHH', seccion: 'Recursos Humanos', tipo: 'TEXTO', seleccionado: false, bloqueado: false },
    { id: 'rrhh_resp_juramentada', nombre: 'rrhh_resp_juramentada', etiqueta: 'Nombre Responsable Declaración Juramentada', seccion: 'Recursos Humanos', tipo: 'TEXTO', seleccionado: false, bloqueado: false },
    { id: 'rrhh_resp_credencial2', nombre: 'rrhh_resp_credencial2', etiqueta: 'Nombre Responsable Credencial / Copia Act.', seccion: 'Recursos Humanos', tipo: 'TEXTO', seleccionado: false, bloqueado: false },
    { id: 'rrhh_resp_acta', nombre: 'rrhh_resp_acta', etiqueta: 'Nombre Responsable Acta Bienes / Ropa', seccion: 'Recursos Humanos', tipo: 'TEXTO', seleccionado: false, bloqueado: false },
    // ── Recepción ──
    { id: 'recepcion_fecha', nombre: 'recepcion_fecha', etiqueta: 'Fecha de Entrega Paz y Salvo', seccion: 'Recepción', tipo: 'FECHA', seleccionado: false, bloqueado: false },
    { id: 'recepcion_hojas', nombre: 'recepcion_hojas', etiqueta: 'N° Hojas Recibidas', seccion: 'Recepción', tipo: 'NUMERO', seleccionado: false, bloqueado: false },
    { id: 'recepcion_servidor', nombre: 'recepcion_servidor', etiqueta: 'Servidor/a que recibe', seccion: 'Recepción', tipo: 'TEXTO', seleccionado: false, bloqueado: false },
    { id: 'recepcion_cargo', nombre: 'recepcion_cargo', etiqueta: 'Cargo del Servidor/a', seccion: 'Recepción', tipo: 'TEXTO', seleccionado: false, bloqueado: false },
    // ── Firma ──
    { id: 'cedula_firmante', nombre: 'cedula_firmante', etiqueta: 'C.C. del Firmante', seccion: 'Firma', tipo: 'TEXTO', seleccionado: false, bloqueado: false },
    { id: 'fecha_firma', nombre: 'fecha_firma', etiqueta: 'Fecha de Firma', seccion: 'Firma', tipo: 'FECHA', seleccionado: false, bloqueado: false },
    // ── Firmas Electrónicas (FirmaEC) ──
    { id: 'tramites_r1', nombre: 'tramites_r1', etiqueta: 'FirmaEC — Trámites: Fila 1', seccion: 'Firmas Electrónicas', tipo: 'FIRMA', seleccionado: false, bloqueado: false },
    { id: 'tramites_r2', nombre: 'tramites_r2', etiqueta: 'FirmaEC — Trámites: Fila 2', seccion: 'Firmas Electrónicas', tipo: 'FIRMA', seleccionado: false, bloqueado: false },
    { id: 'tramites_r3', nombre: 'tramites_r3', etiqueta: 'FirmaEC — Trámites: Fila 3', seccion: 'Firmas Electrónicas', tipo: 'FIRMA', seleccionado: false, bloqueado: false },
    { id: 'tramites_jefe', nombre: 'tramites_jefe', etiqueta: 'FirmaEC — Trámites: Jefe Inmediato', seccion: 'Firmas Electrónicas', tipo: 'FIRMA', seleccionado: false, bloqueado: false },
    { id: 'admin_r1', nombre: 'admin_r1', etiqueta: 'FirmaEC — Administrativa: Fila 1', seccion: 'Firmas Electrónicas', tipo: 'FIRMA', seleccionado: false, bloqueado: false },
    { id: 'admin_r2', nombre: 'admin_r2', etiqueta: 'FirmaEC — Administrativa: Fila 2', seccion: 'Firmas Electrónicas', tipo: 'FIRMA', seleccionado: false, bloqueado: false },
    { id: 'admin_r3', nombre: 'admin_r3', etiqueta: 'FirmaEC — Administrativa: Fila 3', seccion: 'Firmas Electrónicas', tipo: 'FIRMA', seleccionado: false, bloqueado: false },
    { id: 'admin_r4', nombre: 'admin_r4', etiqueta: 'FirmaEC — Administrativa: Fila 4', seccion: 'Firmas Electrónicas', tipo: 'FIRMA', seleccionado: false, bloqueado: false },
    { id: 'admin_dir', nombre: 'admin_dir', etiqueta: 'FirmaEC — Administrativa: Director/a', seccion: 'Firmas Electrónicas', tipo: 'FIRMA', seleccionado: false, bloqueado: false },
    { id: 'tic_r1', nombre: 'tic_r1', etiqueta: 'FirmaEC — TIC: Fila 1', seccion: 'Firmas Electrónicas', tipo: 'FIRMA', seleccionado: false, bloqueado: false },
    { id: 'tic_r2', nombre: 'tic_r2', etiqueta: 'FirmaEC — TIC: Fila 2', seccion: 'Firmas Electrónicas', tipo: 'FIRMA', seleccionado: false, bloqueado: false },
    { id: 'tic_r3', nombre: 'tic_r3', etiqueta: 'FirmaEC — TIC: Fila 3', seccion: 'Firmas Electrónicas', tipo: 'FIRMA', seleccionado: false, bloqueado: false },
    { id: 'tic_r4', nombre: 'tic_r4', etiqueta: 'FirmaEC — TIC: Fila 4', seccion: 'Firmas Electrónicas', tipo: 'FIRMA', seleccionado: false, bloqueado: false },
    { id: 'tic_r5', nombre: 'tic_r5', etiqueta: 'FirmaEC — TIC: Fila 5', seccion: 'Firmas Electrónicas', tipo: 'FIRMA', seleccionado: false, bloqueado: false },
    { id: 'fin_r1', nombre: 'fin_r1', etiqueta: 'FirmaEC — Financiera: Fila 1', seccion: 'Firmas Electrónicas', tipo: 'FIRMA', seleccionado: false, bloqueado: false },
    { id: 'fin_r2', nombre: 'fin_r2', etiqueta: 'FirmaEC — Financiera: Fila 2', seccion: 'Firmas Electrónicas', tipo: 'FIRMA', seleccionado: false, bloqueado: false },
    { id: 'fin_r3', nombre: 'fin_r3', etiqueta: 'FirmaEC — Financiera: Fila 3', seccion: 'Firmas Electrónicas', tipo: 'FIRMA', seleccionado: false, bloqueado: false },
    { id: 'fin_r4', nombre: 'fin_r4', etiqueta: 'FirmaEC — Financiera: Fila 4', seccion: 'Firmas Electrónicas', tipo: 'FIRMA', seleccionado: false, bloqueado: false },
    { id: 'fin_dir', nombre: 'fin_dir', etiqueta: 'FirmaEC — Financiera: Director/a', seccion: 'Firmas Electrónicas', tipo: 'FIRMA', seleccionado: false, bloqueado: false },
    { id: 'seg_r1', nombre: 'seg_r1', etiqueta: 'FirmaEC — Seguridad: Fila 1', seccion: 'Firmas Electrónicas', tipo: 'FIRMA', seleccionado: false, bloqueado: false },
    { id: 'seg_r2', nombre: 'seg_r2', etiqueta: 'FirmaEC — Seguridad: Fila 2', seccion: 'Firmas Electrónicas', tipo: 'FIRMA', seleccionado: false, bloqueado: false },
    { id: 'seg_oficial', nombre: 'seg_oficial', etiqueta: 'FirmaEC — Seguridad: Oficial de Seguridad', seccion: 'Firmas Electrónicas', tipo: 'FIRMA', seleccionado: false, bloqueado: false },
    { id: 'rrhh_r1', nombre: 'rrhh_r1', etiqueta: 'FirmaEC — RRHH: Fila 1', seccion: 'Firmas Electrónicas', tipo: 'FIRMA', seleccionado: false, bloqueado: false },
    { id: 'rrhh_r2', nombre: 'rrhh_r2', etiqueta: 'FirmaEC — RRHH: Fila 2', seccion: 'Firmas Electrónicas', tipo: 'FIRMA', seleccionado: false, bloqueado: false },
    { id: 'rrhh_r3', nombre: 'rrhh_r3', etiqueta: 'FirmaEC — RRHH: Fila 3', seccion: 'Firmas Electrónicas', tipo: 'FIRMA', seleccionado: false, bloqueado: false },
    { id: 'rrhh_r4', nombre: 'rrhh_r4', etiqueta: 'FirmaEC — RRHH: Fila 4', seccion: 'Firmas Electrónicas', tipo: 'FIRMA', seleccionado: false, bloqueado: false },
    { id: 'rrhh_r5', nombre: 'rrhh_r5', etiqueta: 'FirmaEC — RRHH: Fila 5', seccion: 'Firmas Electrónicas', tipo: 'FIRMA', seleccionado: false, bloqueado: false },
    { id: 'rrhh_r6', nombre: 'rrhh_r6', etiqueta: 'FirmaEC — RRHH: Fila 6', seccion: 'Firmas Electrónicas', tipo: 'FIRMA', seleccionado: false, bloqueado: false },
    { id: 'rrhh_r7', nombre: 'rrhh_r7', etiqueta: 'FirmaEC — RRHH: Fila 7', seccion: 'Firmas Electrónicas', tipo: 'FIRMA', seleccionado: false, bloqueado: false },
    { id: 'rrhh_r8', nombre: 'rrhh_r8', etiqueta: 'FirmaEC — RRHH: Fila 8', seccion: 'Firmas Electrónicas', tipo: 'FIRMA', seleccionado: false, bloqueado: false },
    { id: 'rrhh_dir', nombre: 'rrhh_dir', etiqueta: 'FirmaEC — RRHH: Director/a', seccion: 'Firmas Electrónicas', tipo: 'FIRMA', seleccionado: false, bloqueado: false },
    { id: 'recepcion_r1', nombre: 'recepcion_r1', etiqueta: 'FirmaEC — Recepción: Servidor/a que recibe', seccion: 'Firmas Electrónicas', tipo: 'FIRMA', seleccionado: false, bloqueado: false },
  ];

  // ── FormGroup PLANO (1:1 con el HTML) ───────────────────────
  formularioPazSalvo!: FormGroup;

  // ── FormGroup anidado para el ESPEJO A4 (columna derecha) ───
  form!: FormGroup;

  constructor(
    private fb: FormBuilder,
    private cdr: ChangeDetectorRef,
    private formulariosService: FormulariosService,
  ) { }

  // ─────────────────────────────────────────────────────────────
  //  GETTERS derivados
  // ─────────────────────────────────────────────────────────────

  get progressPercent(): number {
    return Math.round(((this.currentStep + 1) / this.steps.length) * 100);
  }

  // ─────────────────────────────────────────────────────────────
  //  LIFECYCLE
  // ─────────────────────────────────────────────────────────────

  ngOnInit(): void {
    this.usuario = this.parseUsuario();
    this.buildForm();
    this.form = this.formularioPazSalvo;
    this.syncEspejo();
    this.listenForConditionalValidators();
    this.loadDraft();
    this.cargarFormularios();
    this.cargarNotificaciones();

    if (this.esAdmin()) {
      this.contenidoVisible = true;
      this.cargarUsuariosDisponibles();
    }
  }

  ngOnDestroy(): void {
    this.destroy$.next();
    this.destroy$.complete();
  }

  private parseUsuario(): any {
    try {
      return JSON.parse(localStorage.getItem('usuario') ?? '{}');
    } catch {
      return {};
    }
  }

  // ─────────────────────────────────────────────────────────────
  //  CONSTRUCCIÓN DEL FORMULARIO PLANO
  //  Cada formControlName del HTML tiene su control aquí.
  // ─────────────────────────────────────────────────────────────

  private buildForm(): void {
    this.formularioPazSalvo = this.fb.group(
      {
        // ── Step 0: Datos Personales ────────────────────────
        nombres_apellidos: [
          '',
          [
            Validators.required,
            Validators.minLength(3),
            Validators.maxLength(80),
            Validators.pattern(/^[a-zA-ZÀ-ÿ\s]+$/),
          ],
        ],
        modalidad: ['', Validators.required],
        cedula: [
          '',
          [Validators.required, Validators.minLength(10), Validators.pattern(/^\d{10}$/), cedulaEcuatorianaValidator()],
        ],
        fecha_ingreso: ['', [Validators.required, noFuturaValidator()]],
        fecha_salida: ['', Validators.required],
        direccion: [
          '',
          [Validators.required, Validators.minLength(5), Validators.maxLength(100)],
        ],
        numero_domicilio: [
          '',
          Validators.pattern(/^[\d\-]{0,10}$/),
        ],
        celular: [
          '',
          [Validators.required, Validators.pattern(/^09\d{8}$/)],
        ],
        emergencia: ['', Validators.pattern(/^09\d{8}$/)],
        email1: ['', [Validators.required, Validators.email]],
        email2: ['', Validators.email],
        provincia: [
          '',
          [Validators.required, Validators.minLength(3), Validators.pattern(/^[a-zA-ZÀ-ÿ\s]+$/)],
        ],
        canton: [
          '',
          [Validators.required, Validators.minLength(3), Validators.pattern(/^[a-zA-ZÀ-ÿ\s]+$/)],
        ],

        // ── Step 0: Dirección / Unidad ──────────────────────
        lugar_trabajo: ['', Validators.required],
        unidad: ['', [Validators.required, Validators.minLength(3), Validators.maxLength(80)]],
        cargo: ['', [Validators.required, Validators.minLength(3), Validators.maxLength(50)]],
        grupo_ocupacional: ['', Validators.required],

        // ── Step 1: Trámites y Unidad ───────────────────────
        tramites_informe: ['', Validators.required],
        tramites_fe_presentacion: ['', Validators.required],
        tramites_losep: ['', Validators.required],
        tramites_admin_contrato: ['', Validators.required],
        tramites_desc_contrato: [''],
        tramites_memo: [''],
        tramites_jefe_inmediato: ['', [Validators.required, Validators.minLength(5)]],
        tramites_quipux_cero: ['', Validators.required],
        tramites_claves_asignadas: ['', Validators.required],
        tramites_acta_claves: ['', Validators.required],
        tramites_servidor_recibe: ['', [Validators.required, Validators.minLength(5)]],
        tramites_obs: [''],
        tramites_nombre_responsable: ['', [Validators.required, Validators.minLength(5)]],
        // Nombres responsables por fila — Trámites
        tramites_nombre_resp1: ['', [Validators.required, Validators.minLength(3), Validators.maxLength(80)]],
        tramites_nombre_resp2: ['', [Validators.required, Validators.minLength(3), Validators.maxLength(80)]],
        tramites_nombre_resp3: ['', [Validators.required, Validators.minLength(3), Validators.maxLength(80)]],

        // ── Step 1: Gestión Administrativa ──────────────────
        admin_informe: ['', Validators.required],
        admin_bienes: ['', Validators.required],
        admin_acta_bienes: ['', Validators.pattern(/^[a-zA-Z0-9\-]*$/)],
        admin_valor_bienes: [null, Validators.min(0)],
        admin_deducibles: ['', Validators.required],
        admin_deducibles_valor: [null],
        admin_pasajes: ['', Validators.required],
        admin_pasajes_valor: [null, Validators.min(0)],
        admin_responsable: ['', [Validators.required, Validators.minLength(5)]],
        // Nombres responsables por fila — Gestión Administrativa
        admin_nombre_resp1: ['', [Validators.required, Validators.minLength(3), Validators.maxLength(80)]],
        admin_nombre_resp2: ['', [Validators.required, Validators.minLength(3), Validators.maxLength(80)]],
        admin_nombre_resp3: ['', [Validators.required, Validators.minLength(3), Validators.maxLength(80)]],
        admin_nombre_resp4: ['', [Validators.required, Validators.minLength(3), Validators.maxLength(80)]],

        // ── Step 1: Gestión TIC ─────────────────────────────
        tic_verificacion: ['', Validators.required],
        tic_ip_fija: ['', Validators.required],
        tic_liberacion: [''],
        tic_retiro_acceso: ['', Validators.required],
        tic_backup: ['', Validators.required],
        tic_ruta_backup: [''],
        tic_cierre_correo: ['', Validators.required],
        tic_esigef: ['', Validators.required],
        tic_spryn: ['', Validators.required],
        tic_esbye: ['', Validators.required],
        tic_quipux: ['', Validators.required],
        tic_tarjeta_cuentas: ['', Validators.required],
        tic_obs: [''],
        tic_responsable: ['', [Validators.required, Validators.minLength(5)]],
        // Nombres responsables por fila — Gestión TIC
        tic_nombre_resp1: ['', [Validators.required, Validators.minLength(3), Validators.maxLength(80)]],
        tic_nombre_resp2: ['', [Validators.required, Validators.minLength(3), Validators.maxLength(80)]],
        tic_nombre_resp3: ['', [Validators.required, Validators.minLength(3), Validators.maxLength(80)]],
        tic_nombre_resp4: ['', [Validators.required, Validators.minLength(3), Validators.maxLength(80)]],

        // ── Step 1: Gestión Financiera ──────────────────────
        fin_saldos: ['', Validators.required],
        fin_saldos_valor: [null, Validators.min(0)],
        fin_saldos_obs: [''],
        fin_anticipo: ['', Validators.required],
        fin_anticipo_valor: [null, Validators.min(0)],
        fin_anticipo_obs: [''],
        fin_recuperacion: ['', Validators.required],
        fin_recuperacion_valor: [null, Validators.min(0)],
        fin_recuperacion_obs: [''],
        fin_devolucion: ['', Validators.required],
        fin_devolucion_valor: [null, Validators.min(0)],
        fin_devolucion_obs: [''],
        fin_director: ['', [Validators.required, Validators.minLength(5)]],
        // Nombres responsables por fila — Gestión Financiera
        fin_nombre_resp1: ['', [Validators.required, Validators.minLength(3), Validators.maxLength(80)]],
        fin_nombre_resp2: ['', [Validators.required, Validators.minLength(3), Validators.maxLength(80)]],
        fin_nombre_resp3: ['', [Validators.required, Validators.minLength(3), Validators.maxLength(80)]],
        fin_nombre_resp4: ['', [Validators.required, Validators.minLength(3), Validators.maxLength(80)]],

        // ── Step 2: Seguridad de la Información ────────────
        seg_archivos: ['', Validators.required],
        seg_archivos_fisicos: ['', Validators.required],
        seg_entrega_copia: ['', Validators.required],
        seg_verificacion_info: ['', Validators.required],
        seg_oficial: ['', [Validators.required, Validators.minLength(5)]],
        seg_responsable: ['', [Validators.required, Validators.minLength(5)]],
        // Nombres responsables por fila — Seguridad
        seg_nombre_resp1: ['', [Validators.required, Validators.minLength(3), Validators.maxLength(80)]],
        seg_nombre_resp2: ['', [Validators.required, Validators.minLength(3), Validators.maxLength(80)]],

        // ── Step 2: Recursos Humanos ────────────────────────
        rrhh_capacitacion: ['', Validators.required],
        rrhh_resp_capacitacion: ['', [Validators.required, Validators.minLength(3), Validators.maxLength(80)]],
        rrhh_evaluacion: ['', Validators.required],
        rrhh_resp_evaluacion: ['', [Validators.required, Validators.minLength(3), Validators.maxLength(80)]],
        rrhh_viajes: ['', Validators.required],
        rrhh_resp_viajes: ['', [Validators.required, Validators.minLength(3), Validators.maxLength(80)]],
        rrhh_siith: ['', Validators.required],
        rrhh_resp_siith: ['', [Validators.required, Validators.minLength(3), Validators.maxLength(80)]],
        rrhh_cursos_eval: [''],
        rrhh_vacaciones: [null, [Validators.required, Validators.min(0)]],
        rrhh_juramentada: ['', Validators.required],
        rrhh_num_certificado: ['', Validators.pattern(/^[a-zA-Z0-9\-]*$/)],
        rrhh_num_declaracion: ['', Validators.pattern(/^[a-zA-Z0-9\-]*$/)],
        rrhh_credencial: ['', Validators.required],
        rrhh_entrega_informe_cd: ['', Validators.required],
        rrhh_ropa_trabajo: ['', Validators.required],
        rrhh_acta_bienes: ['', Validators.required],
        rrhh_director: ['', [Validators.required, Validators.minLength(5)]],
        // Nombres responsables por fila — RRHH (filas 5-8; filas 1-4 ya definidas arriba)
        rrhh_resp_vacaciones: ['', [Validators.required, Validators.minLength(3), Validators.maxLength(80)]],
        rrhh_resp_juramentada: ['', [Validators.required, Validators.minLength(3), Validators.maxLength(80)]],
        rrhh_resp_credencial2: ['', [Validators.required, Validators.minLength(3), Validators.maxLength(80)]],
        rrhh_resp_acta: ['', [Validators.required, Validators.minLength(3), Validators.maxLength(80)]],

        // ── Step 2: Recepción de Documentos ────────────────
        recepcion_fecha: ['', [Validators.required, noFuturaValidator()]],
        recepcion_hojas: [null, [Validators.required, Validators.min(1), Validators.max(50)]],
        recepcion_servidor: ['', [Validators.required, Validators.minLength(5)]],
        recepcion_cargo: ['', [Validators.required, Validators.minLength(3)]],

        // ── Step 2: Autorización y Firma ────────────────────
        cedula_firmante: [
          '',
          [Validators.required, Validators.pattern(/^\d{10}$/), cedulaEcuatorianaValidator()],
        ],
        fecha_firma: ['', [Validators.required, noFuturaValidator()]],
      },
      {
        validators: [
          fechasValidator('fecha_ingreso', 'fecha_salida'),
          emailsDiferentesValidator(),
        ],
      }
    );
  }

  // ─────────────────────────────────────────────────────────────
  //  VALIDATORS CONDICIONALES (reactivos)
  // ─────────────────────────────────────────────────────────────

  private listenForConditionalValidators(): void {
    // tramites_admin_contrato → campos condicionales de contrato
    this.formularioPazSalvo.get('tramites_admin_contrato')!
      .valueChanges.pipe(takeUntil(this.destroy$))
      .subscribe((val: string) => {
        const desc = this.formularioPazSalvo.get('tramites_desc_contrato')!;
        const memo = this.formularioPazSalvo.get('tramites_memo')!;
        if (val === 'SI') {
          desc.setValidators([Validators.required, Validators.minLength(3)]);
          memo.setValidators([Validators.required, Validators.minLength(3)]);
        } else {
          desc.clearValidators();
          memo.clearValidators();
        }
        desc.updateValueAndValidity({ emitEvent: false });
        memo.updateValueAndValidity({ emitEvent: false });
      });

    // admin_deducibles → valor condicional obligatorio
    this.formularioPazSalvo.get('admin_deducibles')!
      .valueChanges.pipe(takeUntil(this.destroy$))
      .subscribe((val: string) => {
        const ctrl = this.formularioPazSalvo.get('admin_deducibles_valor')!;
        if (val === 'SI') {
          ctrl.setValidators([Validators.required, Validators.min(0.01)]);
        } else {
          ctrl.clearValidators();
        }
        ctrl.updateValueAndValidity({ emitEvent: false });
      });

    // tic_backup → ruta obligatoria cuando backup = SI
    this.formularioPazSalvo.get('tic_backup')!
      .valueChanges.pipe(takeUntil(this.destroy$))
      .subscribe((val: string) => {
        const ctrl = this.formularioPazSalvo.get('tic_ruta_backup')!;
        if (val === 'SI') {
          ctrl.setValidators([Validators.required, Validators.minLength(5)]);
        } else {
          ctrl.clearValidators();
        }
        ctrl.updateValueAndValidity({ emitEvent: false });
      });

    // tic_ip_fija → tic_liberacion obligatoria
    this.formularioPazSalvo.get('tic_ip_fija')!
      .valueChanges.pipe(takeUntil(this.destroy$))
      .subscribe((val: string) => {
        const ctrl = this.formularioPazSalvo.get('tic_liberacion')!;
        if (val === 'SI') {
          ctrl.setValidators(Validators.required);
        } else {
          ctrl.clearValidators();
        }
        ctrl.updateValueAndValidity({ emitEvent: false });
      });

    // fin_saldos → fin_saldos_valor obligatorio
    this.formularioPazSalvo.get('fin_saldos')!
      .valueChanges.pipe(takeUntil(this.destroy$))
      .subscribe((val: string) => {
        const ctrl = this.formularioPazSalvo.get('fin_saldos_valor')!;
        ctrl.setValidators(val === 'SI' ? [Validators.required, Validators.min(0.01)] : [Validators.min(0)]);
        ctrl.updateValueAndValidity({ emitEvent: false });
      });

    // fin_anticipo → fin_anticipo_valor obligatorio
    this.formularioPazSalvo.get('fin_anticipo')!
      .valueChanges.pipe(takeUntil(this.destroy$))
      .subscribe((val: string) => {
        const ctrl = this.formularioPazSalvo.get('fin_anticipo_valor')!;
        ctrl.setValidators(val === 'SI' ? [Validators.required, Validators.min(0.01)] : [Validators.min(0)]);
        ctrl.updateValueAndValidity({ emitEvent: false });
      });

    // fin_recuperacion → fin_recuperacion_valor obligatorio
    this.formularioPazSalvo.get('fin_recuperacion')!
      .valueChanges.pipe(takeUntil(this.destroy$))
      .subscribe((val: string) => {
        const ctrl = this.formularioPazSalvo.get('fin_recuperacion_valor')!;
        ctrl.setValidators(val === 'SI' ? [Validators.required, Validators.min(0.01)] : [Validators.min(0)]);
        ctrl.updateValueAndValidity({ emitEvent: false });
      });

    // fin_devolucion → fin_devolucion_valor obligatorio
    this.formularioPazSalvo.get('fin_devolucion')!
      .valueChanges.pipe(takeUntil(this.destroy$))
      .subscribe((val: string) => {
        const ctrl = this.formularioPazSalvo.get('fin_devolucion_valor')!;
        ctrl.setValidators(val === 'SI' ? [Validators.required, Validators.min(0.01)] : [Validators.min(0)]);
        ctrl.updateValueAndValidity({ emitEvent: false });
      });

    // fecha_ingreso → re-validar fecha_salida cuando cambia
    this.formularioPazSalvo.get('fecha_ingreso')!
      .valueChanges.pipe(debounceTime(100), takeUntil(this.destroy$))
      .subscribe(() => {
        this.formularioPazSalvo.get('fecha_salida')!
          .updateValueAndValidity({ emitEvent: false });
      });
  }

  // ─────────────────────────────────────────────────────────────
  //  HELPERS DE ROL
  // ─────────────────────────────────────────────────────────────

  esAdmin(): boolean {
    return this.usuario?.rol === 'Administrador';
  }

  /**
   * Devuelve true si el usuario actual puede editar el campo.
   * - Administrador: puede editar todo.
   * - Usuario normal: solo campos asignados que no estén bloqueados.
   */
  puedeEditarCampo(campo: string): boolean {
    if (this.esAdmin()) return true;
    return (
      this.camposAsignadosUsuario.includes(campo) &&
      !this.camposBloqueados.includes(campo)
    );
  }

  private limpiarTexto(texto: unknown): string {
    return String(texto ?? '').trim().replace(/\s+/g, ' ');
  }

  formatearCedula(valor: any): string {
    return String(valor || '').replace(/\D/g, '') || '—';
  }

  // ─────────────────────────────────────────────────────────────
  //  NAVEGACIÓN POR STEPS
  // ─────────────────────────────────────────────────────────────

  nextStep(): void {
    const errores = this.obtenerErroresPaso(this.currentStep);
    if (errores.length > 0) {
      this.erroresPaso = errores;
      this.marcarCamposPasoTouched(this.currentStep);
      // Retrigger shake: reset then apply in next render frame
      this.shakeErrors = false;
      this.cdr.detectChanges();
      this.shakeErrors = true;
      this.cdr.markForCheck();
      // Scroll to error summary
      setTimeout(() => {
        document.querySelector('.errores-paso-container')
          ?.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
      }, 0);
      // Reset shake class after animation so it can retrigger next click
      setTimeout(() => {
        this.shakeErrors = false;
        this.cdr.markForCheck();
      }, 500);
      return;
    }
    this.erroresPaso = [];
    this.shakeErrors = false;
    if (this.currentStep < this.steps.length - 1) {
      this.currentStep++;
      window.scrollTo({ top: 0, behavior: 'smooth' });
      this.cdr.markForCheck();
    }
  }

  prevStep(): void {
    this.erroresPaso = [];
    if (this.currentStep > 0) {
      this.currentStep--;
      window.scrollTo({ top: 0, behavior: 'smooth' });
      this.cdr.markForCheck();
    }
  }

  goToStep(index: number): void {
    // Solo permite ir a pasos anteriores o al actual
    if (index <= this.currentStep) {
      this.erroresPaso = [];
      this.currentStep = index;
      window.scrollTo({ top: 0, behavior: 'smooth' });
      this.cdr.markForCheck();
    }
  }

  private obtenerErroresPaso(step: number): string[] {
    const errores: string[] = [];
    const campos = this.steps[step]?.campos ?? [];
    campos.forEach(campo => {
      const ctrl = this.formularioPazSalvo.get(campo);
      if (!ctrl) return;

      if (!this.esAdmin() && !this.camposAsignadosUsuario.includes(campo)) return;

      ctrl.markAsTouched();
      ctrl.updateValueAndValidity({ emitEvent: false });

      if (ctrl.invalid) {
        const def = this.camposFormulario.find(c => c.id === campo);
        const label = def?.etiqueta ?? campo;
        const err = ctrl.errors ?? {};

        if (err['required']) errores.push(`${label}: campo obligatorio`);
        else if (err['email']) errores.push(`${label}: formato de email inválido`);
        else if (err['cedulaInvalida']) errores.push(`${label}: cédula con dígito verificador incorrecto`);
        else if (err['pattern']) errores.push(`${label}: formato inválido`);
        else if (err['minlength']) errores.push(`${label}: muy corto (mín. ${err['minlength'].requiredLength} caracteres)`);
        else if (err['maxlength']) errores.push(`${label}: muy largo (máx. ${err['maxlength'].requiredLength} caracteres)`);
        else if (err['min']) errores.push(`${label}: valor mínimo no alcanzado`);
        else if (err['max']) errores.push(`${label}: valor máximo superado`);
        else if (err['fechaFutura']) errores.push(`${label}: la fecha no puede ser futura`);
        else errores.push(`${label}: revise este campo`);
      }
    });

    // Validadores cross-field del grupo
    if (step === 0) {
      if (this.formularioPazSalvo.errors?.['fechasInvalidas']) {
        errores.push('Fechas: la fecha de salida debe ser posterior a la de ingreso');
      }
      if (this.formularioPazSalvo.errors?.['emailsIguales']) {
        errores.push('Email Secundario: no puede ser igual al email principal');
      }
    }
    return [...new Set(errores)];
  }

  private marcarCamposPasoTouched(step: number): void {
    const campos = this.steps[step]?.campos ?? [];
    campos.forEach(campo => {
      const ctrl = this.formularioPazSalvo.get(campo);
      if (ctrl) {
        ctrl.markAsTouched();
        ctrl.markAsDirty();
      }
    });
  }



  // ─────────────────────────────────────────────────────────────
  //  BORRADOR
  // ─────────────────────────────────────────────────────────────

  saveDraft(): void {
    try {
      localStorage.setItem(
        'pazYSalvoDraft',
        JSON.stringify(this.formularioPazSalvo.value)
      );
      this.showSwalToast('Borrador guardado correctamente.', 'success');
    } catch {
      this.showSwalToast('No se pudo guardar el borrador.', 'warning');
    }
  }

  private loadDraft(): void {
    try {
      const draft = localStorage.getItem('pazYSalvoDraft');
      if (draft) {
        this.formularioPazSalvo.patchValue(JSON.parse(draft), { emitEvent: false });
        this.showSwalToast('Se cargó un borrador guardado anteriormente.', 'info');
      }
    } catch {
      // silencioso
    }
  }

  // ─────────────────────────────────────────────────────────────
  //  FIRMA
  // ─────────────────────────────────────────────────────────────

  setFirmaMode(mode: 'canvas' | 'upload'): void {
    this.firmaMode = mode;
    if (mode === 'canvas') {
      setTimeout(() => this.initCanvas(), 60);
    }
    this.cdr.markForCheck();
  }

  private initCanvas(): void {
    if (!this.firmaCanvasRef?.nativeElement) return;
    const canvas = this.firmaCanvasRef.nativeElement;
    this.canvasCtx = canvas.getContext('2d');
    if (!this.canvasCtx) return;
    this.canvasCtx.strokeStyle = '#0d2b5e';
    this.canvasCtx.lineWidth = 2.5;
    this.canvasCtx.lineCap = 'round';
    this.canvasCtx.lineJoin = 'round';
  }

  startDrawing(event: MouseEvent): void {
    if (!this.canvasCtx) this.initCanvas();
    if (!this.canvasCtx) return;
    this.isDrawingCanvas = true;
    const pos = this.getMousePos(event);
    this.canvasCtx.beginPath();
    this.canvasCtx.moveTo(pos.x, pos.y);
    this.hasFirma = true;
    this.firmaRequired = false;
    this.cdr.markForCheck();
  }

  draw(event: MouseEvent): void {
    if (!this.isDrawingCanvas || !this.canvasCtx) return;
    event.preventDefault();
    const pos = this.getMousePos(event);
    this.canvasCtx.lineTo(pos.x, pos.y);
    this.canvasCtx.stroke();
  }

  startDrawingTouch(event: TouchEvent): void {
    event.preventDefault();
    if (!this.canvasCtx) this.initCanvas();
    if (!this.canvasCtx) return;
    this.isDrawingCanvas = true;
    const pos = this.getTouchPos(event);
    this.canvasCtx.beginPath();
    this.canvasCtx.moveTo(pos.x, pos.y);
    this.hasFirma = true;
    this.firmaRequired = false;
    this.cdr.markForCheck();
  }

  drawTouch(event: TouchEvent): void {
    if (!this.isDrawingCanvas || !this.canvasCtx) return;
    event.preventDefault();
    const pos = this.getTouchPos(event);
    this.canvasCtx.lineTo(pos.x, pos.y);
    this.canvasCtx.stroke();
  }

  stopDrawing(): void {
    if (!this.isDrawingCanvas) return;
    this.isDrawingCanvas = false;
    if (
      this.firmaMode === 'canvas' &&
      this.hasFirma &&
      this.firmaCanvasRef?.nativeElement
    ) {
      this.firmaImagePreview = this.firmaCanvasRef.nativeElement.toDataURL('image/png');
      this.cdr.markForCheck();
    }
  }

  clearFirma(): void {
    this.firmaImagePreview = null;
    this.hasFirma = false;
    if (this.canvasCtx && this.firmaCanvasRef?.nativeElement) {
      const c = this.firmaCanvasRef.nativeElement;
      this.canvasCtx.clearRect(0, 0, c.width, c.height);
    }
    this.cdr.markForCheck();
  }

  // ─────────────────────────────────────────────────────────────
  //  FIRMAEC POR SECCIÓN
  // ─────────────────────────────────────────────────────────────

  onFirmaECChange(seccion: string, event: Event): void {
    const input = event.target as HTMLInputElement;
    const file = input.files?.[0];
    if (!file) return;
    if (file.size > 3 * 1024 * 1024) {
      this.showSwalToast('La firma no debe superar 3 MB.', 'warning');
      return;
    }
    const reader = new FileReader();
    reader.onload = (e) => {
      // Compress to max 500×200 px JPEG so base64 stays well below DB column limits
      const img = new Image();
      img.onload = () => {
        const MAX_W = 500, MAX_H = 200;
        const ratio = Math.min(MAX_W / img.width, MAX_H / img.height, 1);
        const cvs = document.createElement('canvas');
        cvs.width = Math.round(img.width * ratio);
        cvs.height = Math.round(img.height * ratio);
        cvs.getContext('2d')!.drawImage(img, 0, 0, cvs.width, cvs.height);
        this.firmasEC[seccion] = cvs.toDataURL('image/jpeg', 0.80);
        this.firmasECRequired[seccion] = false;
        this.cdr.markForCheck();
      };
      img.src = e.target?.result as string;
    };
    reader.readAsDataURL(file);
    input.value = '';
  }

  clearFirmaEC(seccion: string): void {
    this.firmasEC[seccion] = null;
    // Restore upload button if the firma is still assigned and not yet saved
    const asignado = this.esAdmin() || this.camposAsignadosUsuario.includes(seccion);
    const bloqueado = this.camposBloqueados.includes(seccion);
    this.firmasECRequired[seccion] = asignado && !bloqueado;
    this.cdr.markForCheck();
  }

  firmaECOk(seccion: string): boolean {
    return !!this.firmasEC[seccion];
  }

  private validarFirmasEC(): boolean {
    let todasOk = true;

    Object.keys(this.firmasEC).forEach(key => {
      const esCampoAsignado = this.camposAsignadosUsuario.includes(key);
      const estaBloqueado = this.camposBloqueados.includes(key);

      const debeValidar =
        this.esAdmin() ||
        (esCampoAsignado && !estaBloqueado);

      if (debeValidar && !this.firmasEC[key]) {
        this.firmasECRequired[key] = true;
        todasOk = false;
      } else {
        this.firmasECRequired[key] = false;
      }
    });

    if (!todasOk) this.cdr.markForCheck();

    return todasOk;
  }

  onFirmaFileChange(event: Event): void {
    const input = event.target as HTMLInputElement;
    const file = input.files?.[0];
    if (!file) return;

    // Validar tamaño máx 2 MB
    if (file.size > 2 * 1024 * 1024) {
      this.showSwalToast('La imagen no debe superar 2 MB.', 'warning');
      return;
    }

    const reader = new FileReader();
    reader.onload = (e) => {
      this.firmaImagePreview = e.target?.result as string;
      this.hasFirma = true;
      this.firmaRequired = false;
      this.cdr.markForCheck();
    };
    reader.readAsDataURL(file);
  }

  private getMousePos(event: MouseEvent): { x: number; y: number } {
    const canvas = this.firmaCanvasRef.nativeElement;
    const rect = canvas.getBoundingClientRect();
    const scaleX = canvas.width / rect.width;
    const scaleY = canvas.height / rect.height;
    return {
      x: (event.clientX - rect.left) * scaleX,
      y: (event.clientY - rect.top) * scaleY,
    };
  }

  private getTouchPos(event: TouchEvent): { x: number; y: number } {
    const canvas = this.firmaCanvasRef.nativeElement;
    const rect = canvas.getBoundingClientRect();
    const scaleX = canvas.width / rect.width;
    const scaleY = canvas.height / rect.height;
    const touch = event.touches[0];
    return {
      x: (touch.clientX - rect.left) * scaleX,
      y: (touch.clientY - rect.top) * scaleY,
    };
  }

  // ─────────────────────────────────────────────────────────────
  //  VALIDAR Y GUARDAR (botón del último paso)
  // ─────────────────────────────────────────────────────────────

  validarYActualizarEspejo(): void {
    if (!this.formularioSeleccionado?.id) {
      this.alertaRapida('Validación', 'Seleccione un formulario primero.');
      return;
    }

    // Validar FirmaEC de todas las secciones
    if (!this.validarFirmasEC()) {
      this.alertaRapida(
        'Firmas electrónicas requeridas',
        'Debe registrar la FirmaEC del responsable en todas las secciones del formulario.'
      );
      return;
    }

    // Validar firma del servidor saliente obligatoria
    // Validar firma del servidor saliente SOLO si ese campo le corresponde al usuario
    const debeFirmarServidor =
      this.esAdmin() ||
      this.camposAsignadosUsuario.includes('cedula_firmante') ||
      this.camposAsignadosUsuario.includes('fecha_firma');

    if (debeFirmarServidor && !this.hasFirma) {
      this.firmaRequired = true;
      this.cdr.markForCheck();
      this.alertaRapida(
        'Firma requerida',
        'Debe registrar su firma (servidor saliente) para continuar.'
      );
      return;
    }

    this.firmaRequired = false;

    if (this.esAdmin()) {
      this.validarTodoYEnviar();
    } else {
      this.guardarCamposAsignados();
    }
  }

  private validarTodoYEnviar(): void {
    // Marcar todos los campos como tocados para mostrar errores
    Object.keys(this.formularioPazSalvo.controls).forEach(key => {
      this.formularioPazSalvo.get(key)?.markAsTouched();
    });

    if (this.formularioPazSalvo.invalid) {
      this.alertaRapida('Formulario incompleto', 'Revise todos los campos obligatorios antes de validar.');
      this.cdr.markForCheck();
      return;
    }

    Swal.fire({
      icon: 'success',
      title: 'Formulario validado',
      text: 'El formulario Paz y Salvo ha sido validado correctamente.',
      confirmButtonText: 'Aceptar',
    }).then(() => {
      localStorage.removeItem('pazYSalvoDraft');
    });
  }

  private guardarCamposAsignados(): void {
    // Campos de formulario reactivo asignados con valor
    const camposAGuardar = this.camposAsignadosUsuario.filter(campo => {
      if (this.camposBloqueados.includes(campo)) return false;
      const ctrl = this.formularioPazSalvo.get(campo);
      if (!ctrl) return false;
      const val = ctrl.value;
      if (val === null || val === undefined) return false;
      if (typeof val === 'string' && val.trim() === '') return false;
      if (typeof val === 'number' && isNaN(val)) return false;
      return true;
    });

    // FirmaEC asignadas con imagen cargada (no son controles reactivos)
    const firmasAGuardar = this.camposAsignadosUsuario.filter(campo => {
      if (this.camposBloqueados.includes(campo)) return false;
      return (campo in this.firmasEC) && !!this.firmasEC[campo];
    });

    const total = camposAGuardar.length + firmasAGuardar.length;

    if (total === 0) {
      this.alertaRapida('Sin cambios', 'No hay campos ni firmas nuevas para guardar.');
      return;
    }

    // Validar solo los campos reactivos asignados
    let hayErrores = false;
    camposAGuardar.forEach(campo => {
      const ctrl = this.formularioPazSalvo.get(campo);
      ctrl?.markAsTouched();
      ctrl?.updateValueAndValidity({ emitEvent: false });
      if (ctrl?.invalid) hayErrores = true;
    });

    if (hayErrores) {
      this.alertaRapida('Validación', 'Corrija los errores en los campos asignados.');
      this.cdr.markForCheck();
      return;
    }

    this.cargando = true;
    let guardados = 0;
    let errores = 0;

    const onDone = () => {
      if (guardados + errores < total) return;
      this.cargando = false;
      this.cdr.markForCheck();
      if (errores === 0) {
        Swal.fire('Guardado', 'Campos guardados correctamente.', 'success');
        localStorage.removeItem('pazYSalvoDraft');
        this.cargarDetalleFormulario(this.formularioSeleccionado);
      } else if (guardados > 0) {
        Swal.fire('Advertencia', `Se guardaron ${guardados} de ${total}. Fallaron ${errores}.`, 'warning');
      } else {
        Swal.fire('Error', `No se pudo guardar. Fallaron ${errores} campos.`, 'error');
      }
    };

    // Guardar campos reactivos
    camposAGuardar.forEach(campo => {
      const ctrl = this.formularioPazSalvo.get(campo);
      this.formulariosService
        .responder({
          formulario_id: this.formularioSeleccionado.id,
          campo,
          respuesta: this.limpiarTexto(ctrl?.value),
        })
        .subscribe({
          next: () => { guardados++; onDone(); },
          error: (err: any) => { console.error(`Error guardando campo '${campo}':`, err?.error); errores++; onDone(); },
        });
    });

    // Guardar firmasEC (base64 — sin pasar por limpiarTexto)
    firmasAGuardar.forEach(campo => {
      this.formulariosService
        .responder({
          formulario_id: this.formularioSeleccionado.id,
          campo,
          respuesta: this.firmasEC[campo] as string,
        })
        .subscribe({
          next: () => { guardados++; onDone(); },
          error: (err: any) => { console.error(`Error guardando firma '${campo}':`, err?.error); errores++; onDone(); },
        });
    });
  }

  // ─────────────────────────────────────────────────────────────
  //  CARGA DE FORMULARIOS (servicio)
  // ─────────────────────────────────────────────────────────────

  cargarFormularios(): void {
    this.cargando = true;
    this.formulariosService.listar().pipe(
      timeout(8000),
      catchError((err: any) => {
        Swal.fire('Error', err?.error?.mensaje ?? 'Error al cargar formularios.', 'error');
        return of([]);
      }),
      finalize(() => { this.cargando = false; this.cdr.markForCheck(); })
    ).subscribe((data: any[]) => {
      this.formularios = data ?? [];
    });
  }

  crearFormulario(): void {
    if (!this.esAdmin()) {
      this.alertaRapida('Sin permisos', 'Solo el Administrador puede crear formularios.');
      return;
    }
    this.cargando = true;
    this.formulariosService
      .crear({ titulo: 'PAZ Y SALVO', descripcion: 'Formulario oficial de Paz y Salvo' })
      .pipe(
        timeout(8000),
        catchError((err: any) => {
          Swal.fire('Error', err?.error?.mensaje ?? 'Error al crear formulario.', 'error');
          return of(null);
        }),
        finalize(() => { this.cargando = false; this.cdr.markForCheck(); })
      )
      .subscribe((res: any) => {
        if (!res) return;
        Swal.fire('Creado', 'Formulario Paz y Salvo creado correctamente.', 'success');
        this.cargarFormularios();
      });
  }

  verFormulario(f: any): void {
    this.formularioSeleccionado = f;
    this.erroresPaso = [];
    this.currentStep = 0;
    this.cargarDetalleFormulario(f);
    this.cdr.markForCheck();
  }

  cargarDetalleFormulario(f: any): void {
    this.cargando = true;
    this.formularioPazSalvo.reset();

    Object.keys(this.firmasEC).forEach(key => {
      this.firmasEC[key] = null;
      this.firmasECRequired[key] = false;
    });

    this.camposAsignadosUsuario = [];
    this.camposBloqueados = [];
    this.camposYaDesignados = [];
    this.camposFormulario.forEach(c => { c.bloqueado = false; c.seleccionado = false; });

    this.formulariosService.ver(f.id).pipe(
      timeout(8000),
      catchError((err: any) => {
        Swal.fire('Error', err?.error?.mensaje ?? 'No se pudo cargar el formulario.', 'error');
        return of(null);
      }),
      finalize(() => { this.cargando = false; this.cdr.markForCheck(); })
    ).subscribe((data: any) => {
      if (!data) return;

      this.formularioSeleccionado = data.formulario ?? f;
      const preguntas: any[] = data.preguntas ?? [];
      const valores: Record<string, unknown> = {};

      preguntas.forEach((p: any) => {
        const campo: string = p.codigo ?? p.campo ?? p.pregunta ?? '';
        if (!campo || !this.formularioPazSalvo.get(campo)) return;

        this.camposAsignadosUsuario.push(campo);

        if (p.respuesta !== null && p.respuesta !== undefined && p.respuesta !== '') {
          valores[campo] = p.respuesta;
          this.camposBloqueados.push(campo);
        }

        if (p.ya_asignado === 1 || p.asignacion_id) {
          this.camposYaDesignados.push(campo);
        }
      });

      // Deduplicar
      this.camposAsignadosUsuario = [...new Set(this.camposAsignadosUsuario)];
      this.camposBloqueados = [...new Set(this.camposBloqueados)];
      this.camposYaDesignados = [...new Set(this.camposYaDesignados)];

      // Procesar firmasEC (claves que no son controles del formulario reactivo)
      preguntas.forEach((p: any) => {
        const campo: string = p.codigo ?? p.campo ?? p.pregunta ?? '';
        if (!campo || !(campo in this.firmasEC)) return;

        this.camposAsignadosUsuario.push(campo);

        if (p.respuesta !== null && p.respuesta !== undefined && p.respuesta !== '') {
          this.firmasEC[campo] = p.respuesta as string;
          this.camposBloqueados.push(campo);
        }

        if (p.ya_asignado === 1 || p.asignacion_id) {
          this.camposYaDesignados.push(campo);
        }
      });

      // Re-deduplicar tras añadir firmasEC
      this.camposAsignadosUsuario = [...new Set(this.camposAsignadosUsuario)];
      this.camposBloqueados = [...new Set(this.camposBloqueados)];
      this.camposYaDesignados = [...new Set(this.camposYaDesignados)];

      // Marcar campos ya designados como bloqueados en el catálogo de checkboxes (admin)
      this.camposFormulario.forEach(c => {
        c.bloqueado = this.camposYaDesignados.includes(c.id);
        if (c.bloqueado) c.seleccionado = false;
      });

      this.formularioPazSalvo.patchValue(valores, { emitEvent: false });
      this.aplicarPermisosCampos();
      this.cdr.markForCheck();
    });
  }

  /** Habilita / deshabilita controles según rol y asignación. */
  private aplicarPermisosCampos(): void {
    Object.keys(this.formularioPazSalvo.controls).forEach(key => {
      const ctrl = this.formularioPazSalvo.get(key);
      if (!ctrl) return;

      if (this.esAdmin()) {
        ctrl.enable({ emitEvent: false });
      } else if (
        this.camposAsignadosUsuario.includes(key) &&
        !this.camposBloqueados.includes(key)
      ) {
        ctrl.enable({ emitEvent: false });
      } else {
        ctrl.disable({ emitEvent: false });
      }
    });

    // Activar/desactivar firmasEC según asignación y estado de carga
    Object.keys(this.firmasEC).forEach(key => {
      const asignado = this.esAdmin() || this.camposAsignadosUsuario.includes(key);
      const bloqueado = this.camposBloqueados.includes(key);
      // true = mostrar botón de carga / indicador requerido
      this.firmasECRequired[key] = asignado && !bloqueado && !this.firmasEC[key];
    });
  }

  cargarUsuariosDisponibles(): void {
    this.formulariosService.usuariosDisponibles().pipe(
      timeout(8000),
      catchError(() => of([]))
    ).subscribe((data: any[]) => {
      this.usuariosDisponibles = data ?? [];
      this.cdr.markForCheck();
    });
  }

  cargarNotificaciones(): void {
    this.formulariosService.notificaciones().pipe(
      catchError(() => of([]))
    ).subscribe((data: any[]) => {
      this.notificaciones = data ?? [];
      // Si no hay notificaciones sin leer, el contenido se muestra de inmediato
      if (!this.esAdmin() && this.notificaciones.every(n => n.leido)) {
        this.contenidoVisible = true;
      }
      this.cdr.markForCheck();
    });
  }

  marcarNotificacionLeida(n: NotificacionItem): void {
    if (n.leido) return;
    this.formulariosService.marcarNotificacionLeida(n.id).subscribe({
      next: () => {
        n.leido = true;
        this.cdr.markForCheck();
      },
      error: () => { /* silencioso */ },
    });
  }

  marcarTodasLeidas(): void {
    this.notificaciones.filter(n => !n.leido).forEach(n => this.marcarNotificacionLeida(n));
  }

  irAListadoFormularios(): void {
    document.getElementById('listado-formularios')?.scrollIntoView({ behavior: 'smooth', block: 'start' });
  }

  toggleContenido(): void {
    this.contenidoVisible = !this.contenidoVisible;
    this.cdr.markForCheck();
    if (this.contenidoVisible) {
      setTimeout(() => {
        document.getElementById('listado-formularios')
          ?.scrollIntoView({ behavior: 'smooth', block: 'start' });
      }, 200);
    }
  }

  get totalSinLeer(): number {
    return this.notificaciones.filter(n => !n.leido).length;
  }

  get camposPendientesUsuario(): string[] {
    return this.camposAsignadosUsuario.filter(campo =>
      !this.camposBloqueados.includes(campo)
    );
  }

  get formularioTerminado(): boolean {
    return !this.esAdmin()
      && this.camposAsignadosUsuario.length > 0
      && this.camposPendientesUsuario.length === 0;
  }

  get notificacionesPendientes(): any[] {
    return this.notificaciones.filter(n => !n.leido);
  }


  // ─────────────────────────────────────────────────────────────
  //  DESIGNACIÓN DE CAMPOS (panel admin)
  // ─────────────────────────────────────────────────────────────

  camposSeleccionados(): CampoFormulario[] {
    return this.camposFormulario.filter(c => c.seleccionado && !c.bloqueado);
  }

  seleccionarTodosCampos(): void {
    this.camposFormulario.forEach(c => { if (!c.bloqueado) c.seleccionado = true; });
  }

  limpiarSeleccionCampos(): void {
    this.camposFormulario.forEach(c => (c.seleccionado = false));
  }

  designarCampos(): void {
    this.asignacionSubmitted = true;

    if (!this.formularioSeleccionado?.id) {
      this.alertaRapida('Validación', 'Seleccione un formulario primero.');
      return;
    }

    const seleccionados = this.camposSeleccionados();
    if (seleccionados.length === 0) {
      this.alertaRapida('Validación', 'Seleccione al menos un campo disponible.');
      return;
    }

    if (!this.asignacion.usuario_id) {
      this.alertaRapida('Validación', 'Seleccione un usuario destino.');
      return;
    }

    const payload = {
      formulario_id: this.formularioSeleccionado.id,
      campos: seleccionados.map(c => ({
        codigo: c.id,
        pregunta: c.etiqueta,
        seccion: c.seccion,
        tipo: c.tipo,
      })),
      usuario_id: this.asignacion.usuario_id,
      rol: null,
    };

    this.cargando = true;
    this.formulariosService.asignar(payload).pipe(
      timeout(8000),
      catchError((err: any) => {
        Swal.fire({
          icon: 'error',
          title: 'Error al asignar campos',
          text: err?.error?.error || err?.error?.mensaje || 'Error interno del servidor',
          confirmButtonText: 'OK',
          confirmButtonColor: '#dc2626'
        });

        console.error('ERROR REAL ASIGNAR:', err?.error);

        return of(null);
      }),
      finalize(() => { this.cargando = false; this.cdr.markForCheck(); })
    ).subscribe((res: any) => {
      if (!res) return;
      Swal.fire('Enviado', res.mensaje ?? 'Campos designados correctamente.', 'success');
      this.asignacion = { usuario_id: '' };
      this.asignacionSubmitted = false;
      this.limpiarSeleccionCampos();
      this.cargarDetalleFormulario(this.formularioSeleccionado);
    });
  }

  // ─────────────────────────────────────────────────────────────
  //  ELIMINAR FORMULARIO
  // ─────────────────────────────────────────────────────────────

  eliminarFormulario(f: any, event: Event): void {
    event.stopPropagation();

    if (!this.esAdmin()) {
      this.alertaRapida('Sin permisos', 'Solo el Administrador puede eliminar formularios.');
      return;
    }

    Swal.fire({
      title: '¿Eliminar formulario?',
      text: `Esta acción no se puede deshacer: "${f.titulo}"`,
      icon: 'warning',
      showCancelButton: true,
      confirmButtonText: 'Sí, eliminar',
      cancelButtonText: 'Cancelar',
      confirmButtonColor: '#dc2626',
    }).then(result => {
      if (!result.isConfirmed) return;

      this.cargando = true;
      this.formulariosService.eliminar(f.id).pipe(
        timeout(8000),
        catchError((err: any) => {
          Swal.fire('Error', err?.error?.mensaje ?? 'Error al eliminar formulario.', 'error');
          return of(null);
        }),
        finalize(() => { this.cargando = false; this.cdr.markForCheck(); })
      ).subscribe((res: any) => {
        if (!res) return;
        Swal.fire('Eliminado', 'Formulario eliminado correctamente.', 'success');
        if (this.formularioSeleccionado?.id === f.id) {
          this.formularioSeleccionado = null;
        }
        this.cargarFormularios();
      });
    });
  }

  // ─────────────────────────────────────────────────────────────
  //  EXPORTAR / IMPRIMIR
  // ─────────────────────────────────────────────────────────────

  printMirror(): void {
    window.print();
  }

  async exportarHojaEspejoPDF(): Promise<void> {
    const element = document.querySelector('#hojaEspejo') as HTMLElement;
    if (!element) {
      Swal.fire('Error', 'No se encontró el documento para exportar.', 'error');
      return;
    }

    try {
      const html2canvas = (await import('html2canvas')).default;
      const jsPDF = (await import('jspdf')).default;

      const canvas = await html2canvas(element, {
        scale: 2,
        useCORS: true,
        backgroundColor: '#ffffff',
        logging: false,
      });

      const pdf = new jsPDF('p', 'mm', 'a4');
      const imgWidth = 210;
      const pageHeight = 297;
      const imgHeight = (canvas.height * imgWidth) / canvas.width;
      let heightLeft = imgHeight;
      let position = 0;

      const imgData = canvas.toDataURL('image/png');
      pdf.addImage(imgData, 'PNG', 0, position, imgWidth, imgHeight);
      heightLeft -= pageHeight;

      while (heightLeft > 0) {
        position -= pageHeight;
        pdf.addPage();
        pdf.addImage(imgData, 'PNG', 0, position, imgWidth, imgHeight);
        heightLeft -= pageHeight;
      }

      const nombreArchivo = `paz-y-salvo-${this.formularioSeleccionado?.id ?? 'formulario'}.pdf`;
      pdf.save(nombreArchivo);
    } catch {
      Swal.fire('Error', 'No se pudo generar el PDF. Intente de nuevo.', 'error');
    }
  }

  // ─────────────────────────────────────────────────────────────
  //  ACORDEÓN (panel admin)
  // ─────────────────────────────────────────────────────────────

  toggleSeccion(key: string): void {
    this.seccionesAbiertas[key] = !this.seccionesAbiertas[key];
  }

  isOpen(key: string): boolean {
    return !!this.seccionesAbiertas[key];
  }

  // ─────────────────────────────────────────────────────────────
  //  HELPERS INTERNOS
  // ─────────────────────────────────────────────────────────────

  /** Muestra un toast no bloqueante usando SweetAlert2. */
  private showSwalToast(
    mensaje: string,
    icono: 'success' | 'error' | 'warning' | 'info' = 'info'
  ): void {
    Swal.fire({
      toast: true,
      position: 'top-end',
      icon: icono,
      title: mensaje,
      showConfirmButton: false,
      timer: 3500,
      timerProgressBar: true,
    });
  }

  /** Muestra una alerta modal pequeña y no apilable. */
  alertaRapida(titulo: string, texto: string): void {
    if (this.alertaActiva) return;
    this.alertaActiva = true;
    Swal.fire({
      icon: 'warning',
      title: titulo,
      text: texto,
      timer: 2500,
      showConfirmButton: false,
    }).then(() => (this.alertaActiva = false));
  }

  // ─────────────────────────────────────────────────────────────
  //  ESPEJO A4 — FormGroup anidado
  // ─────────────────────────────────────────────────────────────

  private buildEspejoForm(): void {
    this.form = this.fb.group({
      datosPersonales: this.fb.group({
        nombresApellidos: [''],
        cedula: [''],
        numeroDomicilio: [''],
        nominamientoPermanente: [false],
        nominamientoProvisional: [false],
        contratoOcasional: [false],
        contratoTrabajo: [false],
        fechaIngreso: [''],
        fechaSalida: [''],
        numeroCelular: [''],
        numeroEmergencia: [''],
        email1: [''],
        email2: [''],
        direccionDomiciliaria: [''],
        provincia: [''],
        canton: [''],
      }),
      datosUnidad: this.fb.group({
        plantaCentral: [false],
        procesosDesconcentrados: [false],
        direccionUnidad: [''],
        cargoDesempenado: [''],
        grupoOcupacional: [''],
      }),
      entregaGestion: this.fb.group({
        informeGestion: [''],
        tramitesQuipux: [''],
        nombreResp_eg1: [''],
        fePresentacion: [''],
        clavesAcceso: [''],
        nombreResp_eg2: [''],
        entregaArchivo: [''],
        actaClaves: [''],
        nombreResp_eg3: [''],
        esAdminContrato: [''],
        observacionEG: [''],
        nombreResp_eg4: [''],
        descripcionContrato: [''],
        memorandoNuevoAdmin: [''],
        servidorRecibeTramites: [''],
        jefeInmediato: [''],
      }),
      gestionAdministrativa: this.fb.group({
        esAdminContratoAdm: [''],
        entregaInforme: [''],
        nombreResp_ga1: [''],
        bienesMuebles: [''],
        numeroActa: [''],
        nombreResp_ga2: [''],
        valoresDeducibles: [''],
        valorDeducibles: [''],
        nombreResp_ga3: [''],
        pasajesAereos: [''],
        valorPasajes: [''],
        nombreResp_ga4: [''],
      }),
      gestionTIC: this.fb.group({
        verificacionEquipo: [''],
        obsVerificacionEquipo: [''],
        nombreResp_tic1: [''],
        accesoIpFija: [''],
        liberacionIp: [''],
        nombreResp_tic2: [''],
        retiroControlAcceso: [''],
        backupInformacion: [''],
        nombreResp_tic3: [''],
        correoInstitucional: [''],
        esigef: [''],
        quipux: [''],
        spryn: [''],
        esbye: [''],
        nombreResp_tic4: [''],
        tarjetaAcceso: [''],
        obsTarjeta: [''],
        nombreResp_tic5: [''],
      }),
      gestionFinanciera: this.fb.group({
        saldosContables: [''],
        valorSaldosContables: [''],
        obsSaldosContables: [''],
        nombreResp_fin1: [''],
        anticipoSueldos: [''],
        valorAnticipoSueldos: [''],
        obsAnticipoSueldos: [''],
        nombreResp_fin2: [''],
        recuperacionValores: [''],
        valorRecuperacion: [''],
        obsRecuperacion: [''],
        nombreResp_fin3: [''],
        devolucionMuebles: [''],
        valorDevolucion: [''],
        obsDevolucion: [''],
        nombreResp_fin4: [''],
        nombreDirectorFinanciero: [''],
      }),
      seguridadInformacion: this.fb.group({
        archivosDigitales: [''],
        entregaCopiaInforme: [''],
        nombreResp_seg1: [''],
        archivosFisicos: [''],
        verificacionInfoInstitucional: [''],
        nombreResp_seg2: [''],
        nombreOficialSeguridad: [''],
      }),
      recursosHumanos: this.fb.group({
        capacitacion: [''],
        nombreResp_rh1: [''],
        evaluacionDesempeno: [''],
        nombreResp_rh2: [''],
        viajesExterior: [''],
        nombreResp_rh3: [''],
        siith: [''],
        nombreResp_rh4: [''],
        numeroCertificadoVacaciones: [''],
        nombreResp_rh5: [''],
        declaracionJuramentada: [''],
        numeroDeclaracionJuramentada: [''],
        nombreResp_rh6: [''],
        credencialInstitucional: [''],
        copiaActividadesCD: [''],
        nombreResp_rh7: [''],
        actaBienes: [''],
        ropaTrabajo: [''],
        nombreResp_rh8: [''],
        nombreDirectorRRHH: [''],
      }),
      recepcionDocumentos: this.fb.group({
        fechaEntregaPazSalvo: [''],
        numHojasRecibidas: [''],
        nombreQuienRecibe: [''],
        cargoQuienRecibe: [''],
      }),
      autorizacion: this.fb.group({
        cedulaServidor: [''],
      }),
    });
  }

  /** Dispara markForCheck en cada cambio del formulario para actualizar el espejo. */
  private syncEspejo(): void {
    this.formularioPazSalvo.valueChanges
      .pipe(debounceTime(0), takeUntil(this.destroy$))
      .subscribe(() => {
        this.cdr.markForCheck();
      });
  }

  limpiarFormulario(): void {
    this.form.reset();
  }

  imprimir(): void {
    window.print();
  }
}
