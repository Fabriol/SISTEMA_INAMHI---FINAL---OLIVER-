import { Component, OnInit, OnDestroy, ViewChild, ElementRef, ChangeDetectionStrategy, ChangeDetectorRef } from '@angular/core';
import { CommonModule, DatePipe } from '@angular/common';
import {
  FormsModule,
  ReactiveFormsModule,
  FormBuilder,
  FormGroup,
  Validators,
  AbstractControl,
  ValidationErrors,
  ValidatorFn
} from '@angular/forms';
import { RouterModule } from '@angular/router';
import { Subject, of } from 'rxjs';
import { catchError, debounceTime, finalize, takeUntil, timeout } from 'rxjs/operators';
import Swal from 'sweetalert2';
import { FormulariosService } from '../../core/services/formularios';

// ─── Interfaces ───────────────────────────────────────────────────────────────

export interface ToastMessage {
  id: number;
  message: string;
  type: 'success' | 'error' | 'warning' | 'info';
  icon: string;
}

export interface StepConfig {
  title: string;
  description: string;
  formGroups: string[];
}

export interface ChecklistItem {
  key: string;
  label: string;
  shortLabel?: string;
  hasValor?: boolean;
  hasCertificado?: boolean;
}

export interface MirrorData {
  nombresApellidos: string;
  cedula: string;
  numeroDomicilio: string;
  numeroCelular: string;
  numeroEmergencia: string;
  email1: string;
  email2: string;
  direccion: string;
  provincia: string;
  canton: string;
  tipoModalidad: string;
  fechaIngreso: string;
  fechaSalida: string;
  tipoPlanta: string;
  direccionUnidad: string;
  cargoDesempenado: string;
  grupoOcupacional: string;
  jefeInmediato: string;
  gestionDoc: { [key: string]: { estado: string; responsable: string } };
  gestionDocObs: string;
  gestionAdmin: { [key: string]: { estado: string; valor: number | null } };
  nombreDirectorAdmin: string;
  gestionTIC: { [key: string]: { estado: string; observacion: string } };
  sistemas: { [key: string]: boolean };
  gestionFinanciera: { [key: string]: { estado: string; valor: number | null; observacion: string } };
  seguridadInfo: {
    archivosDigitales: string;
    archivosFisicos: string;
    informeActividades: string;
    verificacionInfo: string;
    nombreOficialSeguridad: string;
  };
  gestionRRHH: { [key: string]: { estado: string; numeroCertificado: string } };
  nombreDirectorRRHH: string;
  recepcion: {
    fechaEntrega: string;
    nHojasRecibidas: number | null;
    nombreQuienRecibe: string;
    cargoQuienRecibe: string;
  };
  ccFirmante: string;
  fechaFirma: string;
}

// ─── Validators personalizados ────────────────────────────────────────────────

export function cedulaEcuatorianaValidator(): ValidatorFn {
  return (control: AbstractControl): ValidationErrors | null => {
    const value = control.value as string;
    if (!value) return null;
    if (!/^[a-zA-Z0-9]{10,15}$/.test(value)) return { pattern: true };

    if (/^\d{10}$/.test(value)) {
      const provincia = parseInt(value.substring(0, 2), 10);
      if (provincia < 1 || provincia > 24) return { cedulaInvalida: true };

      const coeficientes = [2, 1, 2, 1, 2, 1, 2, 1, 2];
      let suma = 0;
      for (let i = 0; i < 9; i++) {
        let val = parseInt(value[i], 10) * coeficientes[i];
        if (val >= 10) val -= 9;
        suma += val;
      }
      const digitoVerificador = suma % 10 === 0 ? 0 : 10 - (suma % 10);
      if (digitoVerificador !== parseInt(value[9], 10)) return { cedulaInvalida: true };
    }

    return null;
  };
}

export function fechaPosteriorValidator(startDateKey: string): ValidatorFn {
  return (control: AbstractControl): ValidationErrors | null => {
    if (!control.parent) return null;
    const startDate = control.parent.get(startDateKey)?.value;
    const endDate = control.value;
    if (!startDate || !endDate) return null;
    if (new Date(endDate) <= new Date(startDate)) return { fechaAnterior: true };
    return null;
  };
}

// ─── Componente ───────────────────────────────────────────────────────────────

@Component({
  selector: 'app-formularios',
  standalone: true,
  imports: [CommonModule, FormsModule, ReactiveFormsModule, RouterModule],
  templateUrl: './formularios.html',
  styleUrl: './formularios.scss',
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class Formularios implements OnInit, OnDestroy {
  @ViewChild('firmaCanvas') firmaCanvasRef!: ElementRef<HTMLCanvasElement>;

  private destroy$ = new Subject<void>();
  private toastCounter = 0;
  private ctx: CanvasRenderingContext2D | null = null;
  private isDrawingCanvas = false;
  private alertaActiva = false;

  // ─── Estado UI ──────────────────────────────────────────────
  today = new Date();
  currentStep = 0;
  isSubmitting = false;
  cargando = false;
  firmaMode: 'canvas' | 'upload' | 'firmaec' = 'canvas';
  firmaImagePreview: string | null = null;
  hasFirma = false;
  firmaRequired = false;
  toasts: ToastMessage[] = [];
  mirrorData: Partial<MirrorData> = {};

  // ─── Datos del sistema ──────────────────────────────────────
  formularios: any[] = [];
  formularioSeleccionado: any = null;
  usuariosDisponibles: any[] = [];
  notificaciones: any[] = [];
  pendientes: any[] = [];
  usuario: any = {};
  asignacion = { usuario_id: '' };

  camposAsignadosUsuario: string[] = [];
  camposBloqueados: string[] = [];
  camposYaDesignados: string[] = [];

  // ─── Steps ──────────────────────────────────────────────────
  steps: StepConfig[] = [
    {
      title: 'Información Principal',
      description: 'Datos personales, modalidad y lugar de trabajo',
      formGroups: ['datosPersonales', 'modalidadLaboral', 'lugarTrabajo'],
    },
    {
      title: 'Gestiones',
      description: 'Documental, administrativa, TIC y financiera',
      formGroups: ['gestionDocumental', 'gestionAdministrativa', 'gestionTIC', 'gestionFinanciera'],
    },
    {
      title: 'RRHH, Seguridad y Firma',
      description: 'Seguridad, RRHH, recepción y firma digital',
      formGroups: ['seguridadInfo', 'gestionRRHH', 'recepcionDocumentos', 'autorizacion'],
    },
  ];

  // ─── Catálogos ──────────────────────────────────────────────
  provincias: string[] = [
    'Azuay', 'Bolívar', 'Cañar', 'Carchi', 'Chimborazo', 'Cotopaxi',
    'El Oro', 'Esmeraldas', 'Galápagos', 'Guayas', 'Imbabura', 'Loja',
    'Los Ríos', 'Manabí', 'Morona Santiago', 'Napo', 'Orellana', 'Pastaza',
    'Pichincha', 'Santa Elena', 'Santo Domingo', 'Sucumbíos',
    'Tungurahua', 'Zamora Chinchipe',
  ];

  modalidades = [
    { value: 'NOMBRAMIENTO_PERMANENTE', label: 'Nombramiento Permanente' },
    { value: 'NOMBRAMIENTO_PROVISIONAL', label: 'Nombramiento Provisional' },
    { value: 'CONTRATO_OCASIONAL', label: 'Contrato Ocasional' },
    { value: 'CONTRATO_DE_TRABAJO', label: 'Contrato de Trabajo' },
  ];

  gruposOcupacionales = [
    { value: 'NJS', label: 'NJS — No Jerárquico Superior' },
    { value: 'SRVS', label: 'SRVS — Servidor Público de Servicios' },
    { value: 'SP', label: 'SP — Servidor Público' },
    { value: 'SPA', label: 'SPA — Servidor Público de Apoyo' },
    { value: 'NMNP', label: 'NMNP — No Misional No Profesional' },
    { value: 'OTRO', label: 'Otro' },
  ];

  // ─── Checklist items ────────────────────────────────────────
  gestionDocumentalItems: ChecklistItem[] = [
    { key: 'informeFin', label: 'Entrega informe de fin de gestión con detalle de actividades ejecutadas y pendientes (no requiere aprobación)', shortLabel: 'Informe fin de gestión' },
    { key: 'fePresentacion', label: 'Fe de presentación de la entrega en recepción de documentos del informe de fin de gestión', shortLabel: 'Fe de presentación' },
    { key: 'archivoFisico', label: 'Realiza la entrega de archivo de la documentación física y digital (LOSEP)', shortLabel: 'Archivo físico y digital' },
    { key: 'administradorContrato', label: 'Es administrador de contrato', shortLabel: 'Admin. de contrato' },
    { key: 'tramitesQuipux', label: 'Entrega los trámites asignados en el sistema de gestión documental QUIPUX (bandeja en cero)', shortLabel: 'Trámites QUIPUX en cero' },
    { key: 'clavesAcceso', label: 'Tiene asignado claves de acceso en su unidad', shortLabel: 'Claves de acceso' },
    { key: 'actaClavesUnidad', label: 'Realizó acta entrega de claves de su unidad', shortLabel: 'Acta entrega claves' },
  ];

  gestionAdminItemsLeft: ChecklistItem[] = [
    { key: 'esAdminContrato', label: '¿Es administrador de contrato?' },
    { key: 'bienesMuebles', label: '¿Entregó bienes muebles y equipos?' },
    { key: 'valoresDeducibles', label: '¿Tiene valores pendientes por deducibles?', hasValor: true },
    { key: 'pasajesAereos', label: '¿Tiene pasajes aéreos por justificar?', hasValor: true },
  ];

  gestionAdminItemsRight: ChecklistItem[] = [
    { key: 'realizoEntregaInforme', label: '¿Realizó la entrega del informe?' },
    { key: 'numeroActa', label: 'Número de Acta' },
    { key: 'valorDescontar1', label: 'Valor a Descontar 1', hasValor: true },
    { key: 'valorDescontar2', label: 'Valor a Descontar 2', hasValor: true },
  ];

  get gestionAdminAllItems(): ChecklistItem[] {
    return [...this.gestionAdminItemsLeft, ...this.gestionAdminItemsRight];
  }

  gestionTICItems: ChecklistItem[] = [
    { key: 'verificacionEquipo', label: '¿Se realizó la verificación del equipo informático?' },
    { key: 'accesoIPFija', label: '¿Tiene acceso a IP fija, Wi-Fi y/o móvil?' },
    { key: 'retiroControl', label: 'Retiro de control de acceso (contraseñas de sistemas de información)' },
    { key: 'cierreCuentas', label: '¿Se realizó el cierre de las cuentas?' },
    { key: 'tarjetaAcceso', label: '¿Se realizó la entrega y desactivación de la tarjeta de acceso?' },
    { key: 'backup', label: 'Entrega del backup de la información generada (entregar ruta del backup)' },
  ];

  sistemasItems = [
    { key: 'correoInstitucional', label: 'Correo Institucional' },
    { key: 'quipux', label: 'QUIPUX' },
    { key: 'eSIGEF', label: 'eSIGEF' },
    { key: 'SPRYN', label: 'SPRYN' },
    { key: 'eSByE', label: 'eSByE' },
  ];

  gestionFinancieraItems: ChecklistItem[] = [
    { key: 'saldosContables', label: '¿Tiene valores pendientes de pago por saldos contables? (valores pendientes por viáticos, caja chica, pasajes aéreos)' },
    { key: 'anticipoSueldos', label: '¿Tiene valores pendientes de pago por anticipo de sueldos?' },
    { key: 'recuperacionValores', label: '¿Tiene valores pendientes de pago por recuperación de valores?' },
    { key: 'devolucionMuebles', label: '¿Tiene valores pendientes de pago por devolución de muebles y equipos de oficina?' },
  ];

  gestionRRHHItems: ChecklistItem[] = [
    { key: 'capacitacion', label: 'El responsable de capacitación certifica que el servidor saliente devengó los cursos recibidos en la institución', hasCertificado: true },
    { key: 'evaluacionDesempeno', label: 'El responsable de evaluación del desempeño certifica que al servidor saliente se aplicó la evaluación del desempeño del año en curso' },
    { key: 'viajesExterior', label: 'El responsable de viajes al exterior certifica que el servidor saliente realizó la devengación y/o capacitación de los viajes realizados durante el último año' },
    { key: 'siith', label: 'El responsable del SIITH certifica que el servidor saliente fue desvinculado del puesto que renuncia' },
    { key: 'vacaciones', label: 'El responsable de vacaciones certifica que el servidor saliente cuenta con un total de días acumulados vacaciones' },
    { key: 'constanciaJurada', label: 'Entrega constancia y declaración juramentada de fin de gestión', hasCertificado: true },
    { key: 'credencialInstitucional', label: 'Entrega credencial institucional, porta credencial y colgante' },
    { key: 'actaBienes', label: 'Acta de bienes del custodio' },
    { key: 'copiaActividades', label: 'Entrega copia de información de actividades y respaldos (CD)' },
    { key: 'ropaProteccion', label: 'Entrega ropa de trabajo o equipo de protección' },
  ];

  // ─── Campos del formulario para designación (Admin) ─────────
  camposFormulario: any[] = [
    { id: 'nombres_apellidos', etiqueta: 'Nombres y Apellidos', seccion: 'Datos Personales', tipo: 'TEXTO', seleccionado: false },
    { id: 'modalidad', etiqueta: 'Modalidad Laboral', seccion: 'Datos Personales', tipo: 'SELECT', seleccionado: false },
    { id: 'cedula', etiqueta: 'Cédula / Pasaporte', seccion: 'Datos Personales', tipo: 'TEXTO', seleccionado: false },
    { id: 'fecha_ingreso', etiqueta: 'Fecha de Ingreso', seccion: 'Datos Personales', tipo: 'FECHA', seleccionado: false },
    { id: 'direccion', etiqueta: 'Dirección Domiciliaria', seccion: 'Datos Personales', tipo: 'TEXTO', seleccionado: false },
    { id: 'numero_domicilio', etiqueta: 'Número Domicilio', seccion: 'Datos Personales', tipo: 'TEXTO', seleccionado: false },
    { id: 'fecha_salida', etiqueta: 'Fecha de Salida', seccion: 'Datos Personales', tipo: 'FECHA', seleccionado: false },
    { id: 'celular', etiqueta: 'Número Celular', seccion: 'Datos Personales', tipo: 'TEXTO', seleccionado: false },
    { id: 'emergencia', etiqueta: 'Contacto Emergencia', seccion: 'Datos Personales', tipo: 'TEXTO', seleccionado: false },
    { id: 'email1', etiqueta: 'Email 1', seccion: 'Datos Personales', tipo: 'TEXTO', seleccionado: false },
    { id: 'email2', etiqueta: 'Email 2', seccion: 'Datos Personales', tipo: 'TEXTO', seleccionado: false },
    { id: 'provincia', etiqueta: 'Provincia', seccion: 'Datos Personales', tipo: 'TEXT', seleccionado: false },
    { id: 'canton', etiqueta: 'Cantón', seccion: 'Datos Personales', tipo: 'TEXTO', seleccionado: false },
    { id: 'lugar_trabajo', etiqueta: 'Lugar de Trabajo', seccion: 'Dirección / Unidad', tipo: 'SELECT', seleccionado: false },
    { id: 'unidad', etiqueta: 'Dirección / Unidad', seccion: 'Dirección / Unidad', tipo: 'TEXTO', seleccionado: false },
    { id: 'cargo', etiqueta: 'Cargo Desempeñado', seccion: 'Dirección / Unidad', tipo: 'TEXTO', seleccionado: false },
    { id: 'grupo_ocupacional', etiqueta: 'Grupo Ocupacional', seccion: 'Dirección / Unidad', tipo: 'TEXTO', seleccionado: false },
    { id: 'tramites_informe', etiqueta: 'Entrega informe de fin de gestión', seccion: 'Trámites y Unidad', tipo: 'SELECT', seleccionado: false },
    { id: 'tramites_admin_contrato', etiqueta: '¿Es Administrador de Contrato?', seccion: 'Trámites y Unidad', tipo: 'SELECT', seleccionado: false },
    { id: 'tramites_desc_contrato', etiqueta: 'Descripción del contrato', seccion: 'Trámites y Unidad', tipo: 'TEXTO', seleccionado: false },
    { id: 'tramites_memo', etiqueta: 'Número Memorando', seccion: 'Trámites y Unidad', tipo: 'TEXTO', seleccionado: false },
    { id: 'tramites_jefe_inmediato', etiqueta: 'Nombre del Jefe Inmediato', seccion: 'Trámites y Unidad', tipo: 'TEXTO', seleccionado: false },
    { id: 'tramites_quipux_cero', etiqueta: 'Trámites Quipux / Claves', seccion: 'Trámites y Unidad', tipo: 'SELECT', seleccionado: false },
    { id: 'tramites_servidor_recibe', etiqueta: 'Servidor que recibe trámites', seccion: 'Trámites y Unidad', tipo: 'TEXTO', seleccionado: false },
    { id: 'admin_informe', etiqueta: 'Entrega informe administrativo', seccion: 'Gestión Administrativa', tipo: 'SELECT', seleccionado: false },
    { id: 'admin_bienes', etiqueta: 'Entregó bienes y muebles', seccion: 'Gestión Administrativa', tipo: 'SELECT', seleccionado: false },
    { id: 'admin_acta_bienes', etiqueta: 'Número de Acta', seccion: 'Gestión Administrativa', tipo: 'TEXTO', seleccionado: false },
    { id: 'admin_valor_bienes', etiqueta: 'Valor Bienes', seccion: 'Gestión Administrativa', tipo: 'TEXTO', seleccionado: false },
    { id: 'admin_deducibles', etiqueta: '¿Tiene Deducibles?', seccion: 'Gestión Administrativa', tipo: 'SELECT', seleccionado: false },
    { id: 'admin_deducibles_valor', etiqueta: 'Valor Deducibles', seccion: 'Gestión Administrativa', tipo: 'TEXTO', seleccionado: false },
    { id: 'admin_pasajes', etiqueta: 'Pasajes aéreos', seccion: 'Gestión Administrativa', tipo: 'SELECT', seleccionado: false },
    { id: 'admin_responsable', etiqueta: 'Responsable', seccion: 'Gestión Administrativa', tipo: 'TEXTO', seleccionado: false },
    { id: 'tic_verificacion', etiqueta: 'Verificación Equipo / Accesos', seccion: 'Gestión TIC', tipo: 'SELECT', seleccionado: false },
    { id: 'tic_backup', etiqueta: 'Entrega Backup', seccion: 'Gestión TIC', tipo: 'SELECT', seleccionado: false },
    { id: 'tic_ruta_backup', etiqueta: 'Ruta Backup', seccion: 'Gestión TIC', tipo: 'TEXTO', seleccionado: false },
    { id: 'tic_tarjeta_cuentas', etiqueta: 'Entrega Tarjeta / Cuentas', seccion: 'Gestión TIC', tipo: 'SELECT', seleccionado: false },
    { id: 'tic_responsable', etiqueta: 'Responsable TIC', seccion: 'Gestión TIC', tipo: 'TEXTO', seleccionado: false },
    { id: 'fin_saldos', etiqueta: 'Valores pendientes (Saldos)', seccion: 'Gestión Financiera', tipo: 'SELECT', seleccionado: false },
    { id: 'fin_recuperacion', etiqueta: 'Valores pendientes (Recuperación)', seccion: 'Gestión Financiera', tipo: 'SELECT', seleccionado: false },
    { id: 'fin_director', etiqueta: 'Director/a Financiero/a', seccion: 'Gestión Financiera', tipo: 'TEXTO', seleccionado: false },
    { id: 'seg_archivos', etiqueta: 'Archivos / Info Institucional', seccion: 'Seguridad', tipo: 'SELECT', seleccionado: false },
    { id: 'seg_oficial', etiqueta: 'Oficial de Seguridad', seccion: 'Seguridad', tipo: 'TEXTO', seleccionado: false },
    { id: 'seg_responsable', etiqueta: 'Responsable Seguridad', seccion: 'Seguridad', tipo: 'TEXTO', seleccionado: false },
    { id: 'rrhh_cursos_eval', etiqueta: 'Cursos / Evaluación', seccion: 'Recursos Humanos', tipo: 'SELECT', seleccionado: false },
    { id: 'rrhh_vacaciones', etiqueta: 'Días Vacaciones', seccion: 'Recursos Humanos', tipo: 'TEXTO', seleccionado: false },
    { id: 'rrhh_juramentada', etiqueta: 'Constancia Juramentada', seccion: 'Recursos Humanos', tipo: 'SELECT', seleccionado: false },
    { id: 'rrhh_num_certificado', etiqueta: 'Núm. Certificado', seccion: 'Recursos Humanos', tipo: 'TEXTO', seleccionado: false },
    { id: 'rrhh_num_declaracion', etiqueta: 'Núm. Declaración', seccion: 'Recursos Humanos', tipo: 'TEXTO', seleccionado: false },
    { id: 'rrhh_credencial', etiqueta: 'Credencial / Copias CD', seccion: 'Recursos Humanos', tipo: 'SELECT', seleccionado: false },
    { id: 'rrhh_director', etiqueta: 'Director/a RRHH', seccion: 'Recursos Humanos', tipo: 'TEXTO', seleccionado: false },
    { id: 'recepcion_fecha', etiqueta: 'Fecha de Entrega', seccion: 'Recepción', tipo: 'FECHA', seleccionado: false },
    { id: 'recepcion_hojas', etiqueta: 'Hojas Recibidas', seccion: 'Recepción', tipo: 'TEXTO', seleccionado: false },
    { id: 'recepcion_servidor', etiqueta: 'Servidor que recibe', seccion: 'Recepción', tipo: 'TEXTO', seleccionado: false },
    { id: 'recepcion_cargo', etiqueta: 'Cargo Servidor', seccion: 'Recepción', tipo: 'TEXTO', seleccionado: false },
  ];

  seccionesAbiertas: any = {
    personales: true,
    direccion: false,
    admin: false,
    tramites: false,
    tic: false,
    financiero: false,
    seguridad: false,
    rrhh: false,
    recepcion: false,
  };

  // ─── FormGroups ─────────────────────────────────────────────
  mainForm!: FormGroup;

  get formularioPazSalvo(): FormGroup {
  return this.mainForm;
}

  constructor(
    private fb: FormBuilder,
    private cdr: ChangeDetectorRef,
    private formulariosService: FormulariosService,
  ) {}

  get progressPercent(): number {
    return ((this.currentStep + 1) / this.steps.length) * 100;
  }

  

  // ─── Lifecycle ──────────────────────────────────────────────
  ngOnInit(): void {
    this.usuario = JSON.parse(localStorage.getItem('usuario') || '{}');
    this.buildForm();
    this.listenForMirrorUpdates();
    this.loadDraft();
    this.cargarFormularios();
    this.cargarNotificaciones();

    if (this.esAdmin()) {
      this.cargarUsuariosDisponibles();
    } else {
      this.cargarPendientes();
    }
  }

  ngOnDestroy(): void {
    this.destroy$.next();
    this.destroy$.complete();
  }

  // ─── Form Builder ───────────────────────────────────────────
  private buildForm(): void {
    this.mainForm = this.fb.group({
      datosPersonales: this.buildDatosPersonales(),
      modalidadLaboral: this.buildModalidadLaboral(),
      lugarTrabajo: this.buildLugarTrabajo(),
      gestionDocumental: this.buildGestionDocumental(),
      gestionAdministrativa: this.buildGestionAdministrativa(),
      gestionTIC: this.buildGestionTIC(),
      gestionFinanciera: this.buildGestionFinanciera(),
      seguridadInfo: this.buildSeguridadInfo(),
      gestionRRHH: this.buildGestionRRHH(),
      recepcionDocumentos: this.buildRecepcionDocumentos(),
      autorizacion: this.buildAutorizacion(),
    });
  }

  private buildDatosPersonales(): FormGroup {
    return this.fb.group({
      nombresApellidos: ['', [Validators.required, Validators.minLength(5), Validators.maxLength(100), Validators.pattern(/^[a-zA-ZÀ-ÿ\s]+$/)]],
      cedula: ['', [Validators.required, cedulaEcuatorianaValidator()]],
      numeroDomicilio: [''],
      numeroCelular: ['', [Validators.pattern(/^0[9][0-9]{8}$/)]],
      numeroEmergencia: [''],
      email1: ['', [Validators.required, Validators.email, Validators.maxLength(100)]],
      email2: ['', [Validators.email]],
      direccion: ['', [Validators.required, Validators.minLength(5), Validators.maxLength(200)]],
      provincia: ['', Validators.required],
      canton: ['', [Validators.required, Validators.maxLength(50)]],
    });
  }

  private buildModalidadLaboral(): FormGroup {
    const g = this.fb.group({
      tipoModalidad: ['', Validators.required],
      fechaIngreso: ['', Validators.required],
      fechaSalida: ['', [Validators.required, fechaPosteriorValidator('fechaIngreso')]],
    });
    g.get('fechaIngreso')?.valueChanges.pipe(takeUntil(this.destroy$)).subscribe(() => {
      g.get('fechaSalida')?.updateValueAndValidity();
    });
    return g;
  }

  private buildLugarTrabajo(): FormGroup {
    return this.fb.group({
      tipoPlanta: ['PLANTA_CENTRAL'],
      direccionUnidad: ['', Validators.required],
      cargoDesempenado: ['', Validators.required],
      grupoOcupacional: ['', Validators.required],
      jefeInmediato: ['', Validators.required],
    });
  }

  private buildChecklistGroup(items: ChecklistItem[]): FormGroup {
    const group: Record<string, FormGroup> = {};
    items.forEach(item => {
      const subFields: Record<string, unknown[]> = { estado: [''] };
      if (item.hasValor) subFields['valor'] = [null];
      if (item.hasCertificado) subFields['numeroCertificado'] = [''];
      subFields['responsable'] = [''];
      subFields['observacion'] = [''];
      group[item.key] = this.fb.group(subFields);
    });
    return this.fb.group(group);
  }

  private buildGestionDocumental(): FormGroup {
    const g = this.buildChecklistGroup(this.gestionDocumentalItems);
    (g as any).addControl('observaciones', this.fb.control(''));
    return g;
  }

  private buildGestionAdministrativa(): FormGroup {
    const group: Record<string, unknown> = { nombreDirector: [''] };
    this.gestionAdminAllItems.forEach(item => {
      group[item.key] = this.fb.group({
        estado: [''],
        valor: [null],
        responsable: [''],
      });
    });
    return this.fb.group(group);
  }

  private buildGestionTIC(): FormGroup {
    const group: Record<string, unknown> = {
      sistemas: this.fb.group({
        correoInstitucional: [false],
        quipux: [false],
        eSIGEF: [false],
        SPRYN: [false],
        eSByE: [false],
      }),
    };
    this.gestionTICItems.forEach(item => {
      group[item.key] = this.fb.group({ estado: [''], observacion: [''] });
    });
    return this.fb.group(group);
  }

  private buildGestionFinanciera(): FormGroup {
    const group: Record<string, unknown> = {};
    this.gestionFinancieraItems.forEach(item => {
      group[item.key] = this.fb.group({ estado: [''], valor: [null], observacion: [''] });
    });
    return this.fb.group(group);
  }

  private buildSeguridadInfo(): FormGroup {
    return this.fb.group({
      archivosDigitales: this.fb.group({ estado: [''] }),
      archivosFisicos: this.fb.group({ estado: [''] }),
      informeActividades: this.fb.group({ estado: [''] }),
      verificacionInfo: this.fb.group({ estado: [''] }),
      nombreOficialSeguridad: [''],
    });
  }

  private buildGestionRRHH(): FormGroup {
    const group: Record<string, unknown> = { nombreDirectorRRHH: [''] };
    this.gestionRRHHItems.forEach(item => {
      group[item.key] = this.fb.group({
        estado: [''],
        numeroCertificado: [''],
      });
    });
    return this.fb.group(group);
  }

  private buildRecepcionDocumentos(): FormGroup {
    return this.fb.group({
      fechaEntrega: ['', Validators.required],
      nHojasRecibidas: [null, [Validators.min(1)]],
      nombreQuienRecibe: ['', Validators.required],
      cargoQuienRecibe: [''],
    });
  }

  private buildAutorizacion(): FormGroup {
    return this.fb.group({
      ccFirmante: ['', [Validators.required, cedulaEcuatorianaValidator()]],
      fechaFirma: ['', Validators.required],
      tokenFirmaEC: [''],
    });
  }

  // ─── Mirror reactivo ────────────────────────────────────────
  private listenForMirrorUpdates(): void {
    this.mainForm.valueChanges
      .pipe(debounceTime(150), takeUntil(this.destroy$))
      .subscribe(v => {
        this.updateMirror(v);
        this.cdr.markForCheck();
      });
  }

  private updateMirror(v: Record<string, unknown>): void {
    const dp = (v['datosPersonales'] || {}) as Record<string, string>;
    const ml = (v['modalidadLaboral'] || {}) as Record<string, string>;
    const lt = (v['lugarTrabajo'] || {}) as Record<string, string>;
    const gd = (v['gestionDocumental'] || {}) as Record<string, unknown>;
    const ga = (v['gestionAdministrativa'] || {}) as Record<string, unknown>;
    const tic = (v['gestionTIC'] || {}) as Record<string, unknown>;
    const gf = (v['gestionFinanciera'] || {}) as Record<string, unknown>;
    const si = (v['seguridadInfo'] || {}) as Record<string, unknown>;
    const rrhh = (v['gestionRRHH'] || {}) as Record<string, unknown>;
    const rec = (v['recepcionDocumentos'] || {}) as Record<string, unknown>;
    const au = (v['autorizacion'] || {}) as Record<string, string>;

    this.mirrorData = {
      nombresApellidos: dp['nombresApellidos'],
      cedula: dp['cedula'],
      numeroDomicilio: dp['numeroDomicilio'],
      numeroCelular: dp['numeroCelular'],
      numeroEmergencia: dp['numeroEmergencia'],
      email1: dp['email1'],
      email2: dp['email2'],
      direccion: dp['direccion'],
      provincia: dp['provincia'],
      canton: dp['canton'],
      tipoModalidad: ml['tipoModalidad'],
      fechaIngreso: ml['fechaIngreso'],
      fechaSalida: ml['fechaSalida'],
      tipoPlanta: lt['tipoPlanta'],
      direccionUnidad: lt['direccionUnidad'],
      cargoDesempenado: lt['cargoDesempenado'],
      grupoOcupacional: lt['grupoOcupacional'],
      jefeInmediato: lt['jefeInmediato'],
      gestionDoc: this.extractGestionDoc(gd),
      gestionDocObs: gd['observaciones'] as string,
      gestionAdmin: this.extractGestionAdmin(ga),
      nombreDirectorAdmin: ga['nombreDirector'] as string,
      gestionTIC: this.extractGestionTIC(tic),
      sistemas: (tic['sistemas'] || {}) as { [key: string]: boolean },
      gestionFinanciera: this.extractGestionFinanciera(gf),
      seguridadInfo: {
        archivosDigitales: ((si['archivosDigitales'] as Record<string, string>)?.['estado'] || ''),
        archivosFisicos: ((si['archivosFisicos'] as Record<string, string>)?.['estado'] || ''),
        informeActividades: ((si['informeActividades'] as Record<string, string>)?.['estado'] || ''),
        verificacionInfo: ((si['verificacionInfo'] as Record<string, string>)?.['estado'] || ''),
        nombreOficialSeguridad: si['nombreOficialSeguridad'] as string,
      },
      gestionRRHH: this.extractGestionRRHH(rrhh),
      nombreDirectorRRHH: rrhh['nombreDirectorRRHH'] as string,
      recepcion: {
        fechaEntrega: rec['fechaEntrega'] as string,
        nHojasRecibidas: rec['nHojasRecibidas'] as number | null,
        nombreQuienRecibe: rec['nombreQuienRecibe'] as string,
        cargoQuienRecibe: rec['cargoQuienRecibe'] as string,
      },
      ccFirmante: au['ccFirmante'],
      fechaFirma: au['fechaFirma'],
    };
  }

  private extractGestionDoc(gd: Record<string, unknown>): MirrorData['gestionDoc'] {
    const result: MirrorData['gestionDoc'] = {};
    this.gestionDocumentalItems.forEach(item => {
      const sub = (gd[item.key] || {}) as Record<string, string>;
      result[item.key] = { estado: sub['estado'] || '', responsable: sub['responsable'] || '' };
    });
    return result;
  }

  private extractGestionAdmin(ga: Record<string, unknown>): MirrorData['gestionAdmin'] {
    const result: MirrorData['gestionAdmin'] = {};
    this.gestionAdminAllItems.forEach(item => {
      const sub = (ga[item.key] || {}) as Record<string, unknown>;
      result[item.key] = { estado: (sub['estado'] as string) || '', valor: sub['valor'] as number | null };
    });
    return result;
  }

  private extractGestionTIC(tic: Record<string, unknown>): MirrorData['gestionTIC'] {
    const result: MirrorData['gestionTIC'] = {};
    this.gestionTICItems.forEach(item => {
      const sub = (tic[item.key] || {}) as Record<string, string>;
      result[item.key] = { estado: sub['estado'] || '', observacion: sub['observacion'] || '' };
    });
    return result;
  }

  private extractGestionFinanciera(gf: Record<string, unknown>): MirrorData['gestionFinanciera'] {
    const result: MirrorData['gestionFinanciera'] = {};
    this.gestionFinancieraItems.forEach(item => {
      const sub = (gf[item.key] || {}) as Record<string, unknown>;
      result[item.key] = {
        estado: (sub['estado'] as string) || '',
        valor: sub['valor'] as number | null,
        observacion: (sub['observacion'] as string) || '',
      };
    });
    return result;
  }

  private extractGestionRRHH(rrhh: Record<string, unknown>): MirrorData['gestionRRHH'] {
    const result: MirrorData['gestionRRHH'] = {};
    this.gestionRRHHItems.forEach(item => {
      const sub = (rrhh[item.key] || {}) as Record<string, string>;
      result[item.key] = { estado: sub['estado'] || '', numeroCertificado: sub['numeroCertificado'] || '' };
    });
    return result;
  }

  // ─── Helpers de rol ─────────────────────────────────────────
  esAdmin(): boolean {
    return this.usuario?.rol === 'Administrador';
  }

  limpiarTexto(texto: any): string {
    return String(texto || '').trim().replace(/\s+/g, ' ');
  }

  // ─── Navegación por steps ───────────────────────────────────
  nextStep(): void {
    if (!this.validateCurrentStep()) {
      this.showToast('Corrija los errores antes de continuar.', 'error', '❌');
      this.markCurrentStepDirty();
      return;
    }
    if (this.currentStep < this.steps.length - 1) {
      this.currentStep++;
      this.scrollToTop();
      this.cdr.markForCheck();
    }
  }

  prevStep(): void {
    if (this.currentStep > 0) {
      this.currentStep--;
      this.scrollToTop();
      this.cdr.markForCheck();
    }
  }

  goToStep(index: number): void {
    if (index <= this.currentStep) {
      this.currentStep = index;
      this.scrollToTop();
      this.cdr.markForCheck();
    }
  }

  private scrollToTop(): void {
    window.scrollTo({ top: 0, behavior: 'smooth' });
  }

  private validateCurrentStep(): boolean {
    const groups = this.steps[this.currentStep].formGroups;
    return groups.every(groupName => {
      const group = this.mainForm.get(groupName);
      return group ? group.valid : true;
    });
  }

  private markCurrentStepDirty(): void {
    const groups = this.steps[this.currentStep].formGroups;
    groups.forEach(groupName => {
      const group = this.mainForm.get(groupName) as FormGroup;
      if (group) this.markGroupDirty(group);
    });
  }

  private markGroupDirty(group: FormGroup): void {
    Object.values(group.controls).forEach(ctrl => {
      if (ctrl instanceof FormGroup) {
        this.markGroupDirty(ctrl);
      } else {
        ctrl.markAsDirty();
        ctrl.markAsTouched();
      }
    });
  }

  // ─── Validación helpers ─────────────────────────────────────
  isInvalid(path: string): boolean {
    const ctrl = this.mainForm.get(path);
    return !!ctrl && ctrl.invalid && (ctrl.dirty || ctrl.touched);
  }

  getError(path: string, error: string): boolean {
    return !!this.mainForm.get(path)?.hasError(error);
  }

  puedeEditarCampo(campo: string): boolean {
    if (this.esAdmin()) return true;
    return this.camposAsignadosUsuario.includes(campo) && !this.camposBloqueados.includes(campo);
  }

  // ─── Firma ──────────────────────────────────────────────────
  setFirmaMode(mode: 'canvas' | 'upload' | 'firmaec'): void {
    this.firmaMode = mode;
    if (mode === 'canvas') {
      setTimeout(() => this.initCanvas(), 50);
    }
    this.cdr.markForCheck();
  }

  private initCanvas(): void {
    if (!this.firmaCanvasRef) return;
    const canvas = this.firmaCanvasRef.nativeElement;
    this.ctx = canvas.getContext('2d');
    if (!this.ctx) return;
    this.ctx.strokeStyle = '#0d2b5e';
    this.ctx.lineWidth = 2.5;
    this.ctx.lineCap = 'round';
    this.ctx.lineJoin = 'round';
  }

  startDrawing(event: MouseEvent): void {
    if (!this.ctx) this.initCanvas();
    this.isDrawingCanvas = true;
    this.ctx?.beginPath();
    const pos = this.getCanvasPos(event);
    this.ctx?.moveTo(pos.x, pos.y);
    this.hasFirma = true;
    this.firmaRequired = false;
  }

  draw(event: MouseEvent): void {
    if (!this.isDrawingCanvas || !this.ctx) return;
    event.preventDefault();
    const pos = this.getCanvasPos(event);
    this.ctx.lineTo(pos.x, pos.y);
    this.ctx.stroke();
  }

  startDrawingTouch(event: TouchEvent): void {
    event.preventDefault();
    if (!this.ctx) this.initCanvas();
    this.isDrawingCanvas = true;
    const pos = this.getTouchCanvasPos(event);
    this.ctx?.beginPath();
    this.ctx?.moveTo(pos.x, pos.y);
    this.hasFirma = true;
    this.firmaRequired = false;
  }

  drawTouch(event: TouchEvent): void {
    if (!this.isDrawingCanvas || !this.ctx) return;
    event.preventDefault();
    const pos = this.getTouchCanvasPos(event);
    this.ctx.lineTo(pos.x, pos.y);
    this.ctx.stroke();
  }

  stopDrawing(): void {
    this.isDrawingCanvas = false;
    if (this.firmaMode === 'canvas' && this.hasFirma && this.firmaCanvasRef) {
      this.firmaImagePreview = this.firmaCanvasRef.nativeElement.toDataURL('image/png');
      this.cdr.markForCheck();
    }
  }

  private getCanvasPos(event: MouseEvent): { x: number; y: number } {
    const canvas = this.firmaCanvasRef.nativeElement;
    const rect = canvas.getBoundingClientRect();
    const scaleX = canvas.width / rect.width;
    const scaleY = canvas.height / rect.height;
    return {
      x: (event.clientX - rect.left) * scaleX,
      y: (event.clientY - rect.top) * scaleY,
    };
  }

  private getTouchCanvasPos(event: TouchEvent): { x: number; y: number } {
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

  clearFirma(): void {
    this.firmaImagePreview = null;
    this.hasFirma = false;
    if (this.ctx && this.firmaCanvasRef) {
      const canvas = this.firmaCanvasRef.nativeElement;
      this.ctx.clearRect(0, 0, canvas.width, canvas.height);
    }
    this.cdr.markForCheck();
  }

  onFirmaFileChange(event: Event): void {
    const input = event.target as HTMLInputElement;
    const file = input.files?.[0];
    if (!file) return;
    const reader = new FileReader();
    reader.onload = (e) => {
      this.firmaImagePreview = e.target?.result as string;
      this.hasFirma = true;
      this.firmaRequired = false;
      this.cdr.markForCheck();
    };
    reader.readAsDataURL(file);
  }

  // ─── Submit ─────────────────────────────────────────────────
  onSubmit(): void {
    this.markGroupDirty(this.mainForm as FormGroup);

    if (!this.hasFirma) {
      this.firmaRequired = true;
      this.showToast('La firma digital es OBLIGATORIA.', 'error', '✍️');
      this.cdr.markForCheck();
      return;
    }

    if (this.mainForm.invalid) {
      this.showToast('El formulario tiene errores. Revise todos los campos.', 'error', '❌');
      this.cdr.markForCheck();
      return;
    }

    this.isSubmitting = true;
    this.cdr.markForCheck();

    const payload = {
      ...this.mainForm.value,
      firma: this.firmaImagePreview,
      submittedAt: new Date().toISOString(),
    };

    // Reemplazar con servicio real cuando esté disponible
    setTimeout(() => {
      console.log('[PazYSalvo] Payload:', payload);
      this.isSubmitting = false;
      this.showToast('Formulario enviado correctamente.', 'success', '✅');
      localStorage.removeItem('pazYSalvoDraft');
      this.cdr.markForCheck();
    }, 1800);
  }

  // ─── Draft ──────────────────────────────────────────────────
  saveDraft(): void {
    try {
      localStorage.setItem('pazYSalvoDraft', JSON.stringify(this.mainForm.value));
      this.showToast('Borrador guardado correctamente.', 'info', '💾');
    } catch {
      this.showToast('No se pudo guardar el borrador.', 'warning', '⚠️');
    }
  }

  private loadDraft(): void {
    try {
      const draft = localStorage.getItem('pazYSalvoDraft');
      if (draft) {
        this.mainForm.patchValue(JSON.parse(draft));
        this.showToast('Se cargó un borrador guardado.', 'info', '💾');
      }
    } catch {
      // silencioso
    }
  }

  // ─── Gestión de formularios (servicio) ──────────────────────
  alertaRapida(titulo: string, texto: string): void {
    if (this.alertaActiva) return;
    this.alertaActiva = true;
    Swal.fire({ icon: 'warning', title: titulo, text: texto, timer: 1800, showConfirmButton: false })
      .then(() => (this.alertaActiva = false));
  }

  cargarFormularios(): void {
    this.cargando = true;
    this.formulariosService.listar().pipe(
      timeout(4000),
      catchError((err: any) => {
        Swal.fire('Error', err.error?.mensaje || 'Error al cargar formularios', 'error');
        return of([]);
      }),
      finalize(() => { this.cargando = false; this.cdr.markForCheck(); })
    ).subscribe((data: any[]) => { this.formularios = data || []; });
  }

  crearFormulario(): void {
    if (!this.esAdmin()) {
      this.alertaRapida('Sin permisos', 'Solo el Administrador puede crear formularios.');
      return;
    }
    this.cargando = true;
    this.formulariosService.crear({ titulo: 'PAZ Y SALVO', descripcion: 'Formulario oficial de Paz y Salvo' }).pipe(
      timeout(4000),
      catchError((err: any) => {
        Swal.fire('Error', err.error?.mensaje || 'Error al crear formulario', 'error');
        return of(null);
      }),
      finalize(() => { this.cargando = false; this.cdr.markForCheck(); })
    ).subscribe((res: any) => {
      if (!res) return;
      Swal.fire('Creado', 'Formulario Paz y Salvo creado correctamente.', 'success');
      this.cargarFormularios();
    });
  }

  verFormulario(f: any): void {
    this.formularioSeleccionado = f;
    this.cargarDetalleFormulario(f);
  }

  cargarDetalleFormulario(f: any): void {
    this.cargando = true;
    this.mainForm.reset();
    this.camposAsignadosUsuario = [];
    this.camposBloqueados = [];
    this.camposYaDesignados = [];
    this.camposFormulario.forEach(c => { c.bloqueado = false; c.seleccionado = false; });

    this.formulariosService.ver(f.id).pipe(
      timeout(4000),
      catchError((err: any) => {
        Swal.fire('Error', err.error?.mensaje || 'No se pudo cargar formulario', 'error');
        return of(null);
      }),
      finalize(() => { this.cargando = false; this.cdr.markForCheck(); })
    ).subscribe((data: any) => {
      if (!data) return;
      this.formularioSeleccionado = data.formulario;
      const preguntas = data.preguntas || [];
      const valores: any = {};

      preguntas.forEach((p: any) => {
        const campo = p.codigo || p.campo || p.pregunta;
        if (campo && this.mainForm.get(campo)) {
          this.camposAsignadosUsuario.push(campo);
          if (p.respuesta) { valores[campo] = p.respuesta; this.camposBloqueados.push(campo); }
          if (p.ya_asignado === 1 || p.asignacion_id) this.camposYaDesignados.push(campo);
        }
      });

      this.camposYaDesignados = [...new Set(this.camposYaDesignados)];
      this.camposFormulario.forEach(c => {
        c.bloqueado = this.camposYaDesignados.includes(c.id);
        if (c.bloqueado) c.seleccionado = false;
      });
      this.camposAsignadosUsuario = [...new Set(this.camposAsignadosUsuario)];
      this.camposBloqueados = [...new Set(this.camposBloqueados)];

      this.mainForm.patchValue(valores);
      this.bloquearCamposNoPermitidos();
      this.cdr.markForCheck();
    });
  }

  bloquearCamposNoPermitidos(): void {
    const recorrerGrupo = (group: FormGroup) => {
      Object.keys(group.controls).forEach(key => {
        const ctrl = group.get(key);
        if (ctrl instanceof FormGroup) {
          recorrerGrupo(ctrl);
        } else {
          if (this.esAdmin()) {
            ctrl?.enable({ emitEvent: false });
          } else if (!this.camposAsignadosUsuario.includes(key) || this.camposBloqueados.includes(key)) {
            ctrl?.disable({ emitEvent: false });
          } else {
            ctrl?.enable({ emitEvent: false });
          }
        }
      });
    };
    recorrerGrupo(this.mainForm);
  }

  cargarUsuariosDisponibles(): void {
    this.formulariosService.usuariosDisponibles().pipe(
      timeout(4000), catchError(() => of([]))
    ).subscribe((data: any[]) => { this.usuariosDisponibles = data || []; });
  }

  cargarPendientes(): void {
    this.formulariosService.misPendientes().pipe(catchError(() => of([])))
      .subscribe((data: any[]) => { this.pendientes = data || []; });
  }

  cargarNotificaciones(): void {
    this.formulariosService.notificaciones().pipe(catchError(() => of([])))
      .subscribe((data: any[]) => { this.notificaciones = data || []; });
  }

  marcarNotificacionLeida(n: any): void {
    this.formulariosService.marcarNotificacionLeida(n.id).subscribe(() => { n.leido = 1; });
  }

  // ─── Designación de campos ──────────────────────────────────
  camposSeleccionados(): any[] {
    return this.camposFormulario.filter(c => c.seleccionado && !c.bloqueado);
  }

  seleccionarTodosCampos(): void {
    this.camposFormulario.forEach(c => { if (!c.bloqueado) c.seleccionado = true; });
  }

  limpiarSeleccionCampos(): void {
    this.camposFormulario.forEach(c => (c.seleccionado = false));
  }

  designarCampos(): void {
    const bloqueadosSeleccionados = this.camposFormulario.filter(c => c.seleccionado && c.bloqueado);
    if (bloqueadosSeleccionados.length > 0) {
      this.alertaRapida('Bloqueado', 'No puede designar campos que ya fueron asignados.');
      return;
    }
    if (!this.esAdmin()) return;
    if (!this.formularioSeleccionado?.id) {
      this.alertaRapida('Validación', 'Seleccione un formulario primero.');
      return;
    }
    const seleccionados = this.camposSeleccionados();
    if (seleccionados.length === 0) {
      this.alertaRapida('Validación', 'Seleccione al menos un campo.');
      return;
    }
    if (!this.asignacion.usuario_id) {
      this.alertaRapida('Validación', 'Seleccione un usuario destino.');
      return;
    }

    const data = {
      formulario_id: this.formularioSeleccionado.id,
      campos: seleccionados.map(c => ({ codigo: c.id, pregunta: c.etiqueta, seccion: c.seccion, tipo: c.tipo })),
      usuario_id: this.asignacion.usuario_id,
      rol: null,
    };

    this.cargando = true;
    this.formulariosService.asignar(data).pipe(
      timeout(4000),
      catchError((err: any) => {
        Swal.fire('Error', err.error?.mensaje || err.error?.error || 'Error al designar campos', 'error');
        return of(null);
      }),
      finalize(() => { this.cargando = false; this.cdr.markForCheck(); })
    ).subscribe((res: any) => {
      if (!res) return;
      Swal.fire('Enviado', res.mensaje || 'Campos designados correctamente.', 'success');
      this.asignacion = { usuario_id: '' };
      this.limpiarSeleccionCampos();
      this.cargarDetalleFormulario(this.formularioSeleccionado);
    });
  }

  // ─── Guardar respuestas ─────────────────────────────────────
  validarYActualizarEspejo(): void {
    if (!this.formularioSeleccionado?.id) {
      this.alertaRapida('Validación', 'Seleccione un formulario primero.');
      return;
    }
    if (!this.validarPazSalvo()) return;
    if (!this.esAdmin()) {
      this.guardarCamposAsignados();
      return;
    }
    Swal.fire('Correcto', 'Formulario validado correctamente.', 'success');
  }

  validarPazSalvo(): boolean {
    if (this.esAdmin()) {
      if (this.mainForm.invalid) {
        this.mainForm.markAllAsTouched();
        this.alertaRapida('Validación', 'Revise todos los campos obligatorios.');
        return false;
      }
      return true;
    }

    const camposEditables = this.camposAsignadosUsuario.filter(c => !this.camposBloqueados.includes(c));
    if (camposEditables.length === 0) {
      this.alertaRapida('Sin campos', 'No tiene campos pendientes para llenar.');
      return false;
    }

    for (const campo of camposEditables) {
      const control = this.mainForm.get(campo);
      if (!control) continue;
      control.markAsTouched();
      control.updateValueAndValidity();
      if (control.invalid || !this.limpiarTexto(control.value)) {
        this.alertaRapida('Validación', `Revise el campo: ${campo}`);
        return false;
      }
    }
    return true;
  }

  guardarCamposAsignados(): void {
    const campos = this.camposAsignadosUsuario.filter(campo => {
      const control = this.mainForm.get(campo);
      return !this.camposBloqueados.includes(campo) && control && this.limpiarTexto(control.value) !== '';
    });

    if (campos.length === 0) {
      this.alertaRapida('Validación', 'No hay campos nuevos para guardar.');
      return;
    }

    let guardados = 0;
    campos.forEach(campo => {
      const control = this.mainForm.get(campo);
      this.formulariosService.responder({
        formulario_id: this.formularioSeleccionado.id,
        campo,
        respuesta: this.limpiarTexto(control?.value),
      }).subscribe({
        next: () => {
          guardados++;
          if (guardados === campos.length) {
            Swal.fire('Guardado', 'Campos asignados guardados correctamente.', 'success');
            this.cargarDetalleFormulario(this.formularioSeleccionado);
            this.cargarPendientes();
          }
        },
        error: (err) => {
          Swal.fire('Error', err?.error?.mensaje || err?.error?.error || 'Error al guardar campos', 'error');
        },
      });
    });
  }

  // ─── Eliminar formulario ────────────────────────────────────
  eliminarFormulario(f: any, event: Event): void {
    event.stopPropagation();
    if (!this.esAdmin()) {
      this.alertaRapida('Sin permisos', 'Solo el Administrador puede eliminar formularios.');
      return;
    }
    Swal.fire({
      title: '¿Eliminar formulario?',
      text: `Se eliminará: ${f.titulo}`,
      icon: 'warning',
      showCancelButton: true,
      confirmButtonText: 'Sí, eliminar',
      cancelButtonText: 'Cancelar',
    }).then(result => {
      if (!result.isConfirmed) return;
      this.cargando = true;
      this.formulariosService.eliminar(f.id).pipe(
        timeout(4000),
        catchError((err: any) => {
          Swal.fire('Error', err.error?.mensaje || 'Error al eliminar formulario', 'error');
          return of(null);
        }),
        finalize(() => { this.cargando = false; this.cdr.markForCheck(); })
      ).subscribe((res: any) => {
        if (!res) return;
        Swal.fire('Eliminado', 'Formulario eliminado correctamente.', 'success');
        if (this.formularioSeleccionado?.id === f.id) this.formularioSeleccionado = null;
        this.cargarFormularios();
      });
    });
  }

  // ─── Exportar PDF ────────────────────────────────────────────
  async exportarHojaEspejoPDF(): Promise<void> {
    if (!this.formularioSeleccionado?.id) return;
    const html2canvas = (await import('html2canvas')).default;
    const jsPDF = (await import('jspdf')).default;
    const element = document.querySelector('.a4-page') as HTMLElement;
    if (!element) { Swal.fire('Error', 'No se encontró el documento A4', 'error'); return; }
    const canvas = await html2canvas(element, { scale: 2, useCORS: true, backgroundColor: '#ffffff' });
    const imgData = canvas.toDataURL('image/png');
    const pdf = new jsPDF('p', 'mm', 'a4');
    const imgWidth = 210;
    const imgHeight = (canvas.height * imgWidth) / canvas.width;
    pdf.addImage(imgData, 'PNG', 0, 0, imgWidth, imgHeight);
    pdf.save('formulario-paz-y-salvo.pdf');
  }

  descargarPDF(): void {
    if (!this.formularioSeleccionado?.id) {
      this.alertaRapida('Validación', 'Seleccione un formulario primero.');
      return;
    }
    window.open(`http://localhost:5000/api/formularios/${this.formularioSeleccionado.id}/pdf`, '_blank');
  }

  printMirror(): void {
    window.print();
  }

  // ─── Acordeón ────────────────────────────────────────────────
  toggleSeccion(key: string): void {
    this.seccionesAbiertas[key] = !this.seccionesAbiertas[key];
  }

  isOpen(key: string): boolean {
    return this.seccionesAbiertas[key];
  }

  // ─── Toasts ─────────────────────────────────────────────────
  showToast(message: string, type: ToastMessage['type'], icon: string): void {
    const id = ++this.toastCounter;
    const icons: Record<ToastMessage['type'], string> = {
      success: '✅', error: '❌', warning: '⚠️', info: 'ℹ️',
    };
    this.toasts.push({ id, message, type, icon: icon || icons[type] });
    this.cdr.markForCheck();
    setTimeout(() => this.removeToast(id), 4500);
  }

  removeToast(id: number): void {
    this.toasts = this.toasts.filter(t => t.id !== id);
    this.cdr.markForCheck();
  }
}