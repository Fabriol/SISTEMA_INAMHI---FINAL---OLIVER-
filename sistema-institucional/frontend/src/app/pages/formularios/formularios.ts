// paz-y-salvo.component.ts
import {
  Component,
  OnInit,
  OnDestroy,
  ViewChild,
  ElementRef,
  ChangeDetectionStrategy,
  ChangeDetectorRef,
} from '@angular/core';
import { CommonModule, DatePipe } from '@angular/common';
import {
  ReactiveFormsModule,
  FormBuilder,
  FormGroup,
  Validators,
  AbstractControl,
  ValidationErrors,
  ValidatorFn,
} from '@angular/forms';
import { Subject, auditTime } from 'rxjs';
import { takeUntil, distinctUntilChanged } from 'rxjs/operators';
import { RouterModule } from '@angular/router';


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

// ─── MirrorData extendida con TODAS las secciones ────────────────────────────

export interface MirrorData {
  // Paso 1 — Datos Personales
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
  // Modalidad Laboral
  tipoModalidad: string;
  fechaIngreso: string;
  fechaSalida: string;
  // Lugar de Trabajo
  tipoPlanta: string;
  direccionUnidad: string;
  cargoDesempenado: string;
  grupoOcupacional: string;
  jefeInmediato: string;
  // Paso 2 — Gestión Documental
  gestionDoc: { [key: string]: { estado: string; responsable: string } };
  gestionDocObs: string;
  // Gestión Administrativa
  gestionAdmin: { [key: string]: { estado: string; valor: number | null } };
  nombreDirectorAdmin: string;
  // Gestión TIC
  gestionTIC: { [key: string]: { estado: string; observacion: string } };
  sistemas: { [key: string]: boolean };
  // Gestión Financiera
  gestionFinanciera: { [key: string]: { estado: string; valor: number | null; observacion: string } };
  // Paso 3 — Seguridad Info
  seguridadInfo: {
    archivosDigitales: string;
    archivosFisicos: string;
    informeActividades: string;
    verificacionInfo: string;
    nombreOficialSeguridad: string;
  };
  // Gestión RRHH
  gestionRRHH: { [key: string]: { estado: string; numeroCertificado: string } };
  nombreDirectorRRHH: string;
  // Recepción de Documentos
  recepcion: {
    fechaEntrega: string;
    nHojasRecibidas: number | null;
    nombreQuienRecibe: string;
    cargoQuienRecibe: string;
  };
  // Autorización y Firma
  ccFirmante: string;
  fechaFirma: string;
}

// ─── Validators personalizados ────────────────────────────────────────────────

export function cedulaEcuatorianaValidator(): ValidatorFn {
  return (control: AbstractControl): ValidationErrors | null => {
    const value = control.value as string;
    if (!value) return null;
    if (!/^\d{10,13}$/.test(value)) return { pattern: true };

    if (value.length === 10) {
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
  selector: 'app-paz-y-salvo',
  standalone: true,
  imports: [CommonModule, ReactiveFormsModule, DatePipe, RouterModule],
  templateUrl: './formularios.html',
  styleUrls: ['./formularios.scss'],
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class Formularios implements OnInit, OnDestroy {
  @ViewChild('firmaCanvas') firmaCanvasRef!: ElementRef<HTMLCanvasElement>;

  private destroy$ = new Subject<void>();
  private toastCounter = 0;
  private ctx: CanvasRenderingContext2D | null = null;
  private isDrawingCanvas = false;

  // ─── Estado UI ──────────────────────────────────────────────
  today = new Date();
  currentStep = 0;
  isSubmitting = false;
  firmaMode: 'canvas' | 'upload' | 'firmaec' = 'canvas';
  firmaImagePreview: string | null = null;
  hasFirma = false;
  firmaRequired = false;
  toasts: ToastMessage[] = [];
  mirrorData: Partial<MirrorData> = {};

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

  /** Getter para unir ambas columnas en el espejo */
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

  // ─── FormGroup principal ────────────────────────────────────
  mainForm!: FormGroup;

  constructor(
    private fb: FormBuilder,
    private cdr: ChangeDetectorRef,
  ) { }

  get progressPercent(): number {
    return ((this.currentStep + 1) / this.steps.length) * 100;
  }

  // ─── Lifecycle ──────────────────────────────────────────────
  ngOnInit(): void {
    this.buildForm();

    const draft = this.getDraftFast();
    if (draft) {
      this.mainForm.patchValue(draft, { emitEvent: false });
    }

    this.updateMirror(this.mainForm.getRawValue());
    this.listenForMirrorUpdates();

    setTimeout(() => this.initCanvas(), 0);
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
    (g as unknown as FormGroup & { addControl: Function }).addControl('observaciones', this.fb.control(''));
    return g;
  }

  private buildGestionAdministrativa(): FormGroup {
    const group: Record<string, unknown> = { nombreDirector: [''] };
    [...this.gestionAdminItemsLeft, ...this.gestionAdminItemsRight].forEach(item => {
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
      .pipe(
        auditTime(250),
        distinctUntilChanged((a, b) => JSON.stringify(a) === JSON.stringify(b)),
        takeUntil(this.destroy$)
      )
      .subscribe(v => {
        this.updateMirror(v);
        this.cdr.markForCheck();
      });
  }

  private getDraftFast(): any | null {
    try {
      const draft = localStorage.getItem('pazYSalvoDraft');
      return draft ? JSON.parse(draft) : null;
    } catch {
      return null;
    }
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
      // ── Datos Personales ──
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
      // ── Modalidad Laboral ──
      tipoModalidad: ml['tipoModalidad'],
      fechaIngreso: ml['fechaIngreso'],
      fechaSalida: ml['fechaSalida'],
      // ── Lugar de Trabajo ──
      tipoPlanta: lt['tipoPlanta'],
      direccionUnidad: lt['direccionUnidad'],
      cargoDesempenado: lt['cargoDesempenado'],
      grupoOcupacional: lt['grupoOcupacional'],
      jefeInmediato: lt['jefeInmediato'],
      // ── Gestión Documental ──
      gestionDoc: this.extractGestionDoc(gd),
      gestionDocObs: gd['observaciones'] as string,
      // ── Gestión Administrativa ──
      gestionAdmin: this.extractGestionAdmin(ga),
      nombreDirectorAdmin: ga['nombreDirector'] as string,
      // ── Gestión TIC ──
      gestionTIC: this.extractGestionTIC(tic),
      sistemas: (tic['sistemas'] || {}) as { [key: string]: boolean },
      // ── Gestión Financiera ──
      gestionFinanciera: this.extractGestionFinanciera(gf),
      // ── Seguridad Info ──
      seguridadInfo: {
        archivosDigitales: ((si['archivosDigitales'] as Record<string, string>)?.['estado'] || ''),
        archivosFisicos: ((si['archivosFisicos'] as Record<string, string>)?.['estado'] || ''),
        informeActividades: ((si['informeActividades'] as Record<string, string>)?.['estado'] || ''),
        verificacionInfo: ((si['verificacionInfo'] as Record<string, string>)?.['estado'] || ''),
        nombreOficialSeguridad: si['nombreOficialSeguridad'] as string,
      },
      // ── Gestión RRHH ──
      gestionRRHH: this.extractGestionRRHH(rrhh),
      nombreDirectorRRHH: rrhh['nombreDirectorRRHH'] as string,
      // ── Recepción de Documentos ──
      recepcion: {
        fechaEntrega: rec['fechaEntrega'] as string,
        nHojasRecibidas: rec['nHojasRecibidas'] as number | null,
        nombreQuienRecibe: rec['nombreQuienRecibe'] as string,
        cargoQuienRecibe: rec['cargoQuienRecibe'] as string,
      },
      // ── Autorización ──
      ccFirmante: au['ccFirmante'],
      fechaFirma: au['fechaFirma'],
    };
  }

  private extractGestionDoc(
    gd: Record<string, unknown>
  ): MirrorData['gestionDoc'] {
    const result: MirrorData['gestionDoc'] = {};
    this.gestionDocumentalItems.forEach(item => {
      const sub = (gd[item.key] || {}) as Record<string, string>;
      result[item.key] = {
        estado: sub['estado'] || '',
        responsable: sub['responsable'] || '',
      };
    });
    return result;
  }

  private extractGestionAdmin(
    ga: Record<string, unknown>
  ): MirrorData['gestionAdmin'] {
    const result: MirrorData['gestionAdmin'] = {};
    this.gestionAdminAllItems.forEach(item => {
      const sub = (ga[item.key] || {}) as Record<string, unknown>;
      result[item.key] = {
        estado: (sub['estado'] as string) || '',
        valor: sub['valor'] as number | null,
      };
    });
    return result;
  }

  private extractGestionTIC(
    tic: Record<string, unknown>
  ): MirrorData['gestionTIC'] {
    const result: MirrorData['gestionTIC'] = {};
    this.gestionTICItems.forEach(item => {
      const sub = (tic[item.key] || {}) as Record<string, string>;
      result[item.key] = {
        estado: sub['estado'] || '',
        observacion: sub['observacion'] || '',
      };
    });
    return result;
  }

  private extractGestionFinanciera(
    gf: Record<string, unknown>
  ): MirrorData['gestionFinanciera'] {
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

  private extractGestionRRHH(
    rrhh: Record<string, unknown>
  ): MirrorData['gestionRRHH'] {
    const result: MirrorData['gestionRRHH'] = {};
    this.gestionRRHHItems.forEach(item => {
      const sub = (rrhh[item.key] || {}) as Record<string, string>;
      result[item.key] = {
        estado: sub['estado'] || '',
        numeroCertificado: sub['numeroCertificado'] || '',
      };
    });
    return result;
  }

  // ─── Navegación ─────────────────────────────────────────────
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

    // Simular envío — reemplazar con servicio real
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
      localStorage.setItem('pazYSalvoDraft', JSON.stringify(this.mainForm.getRawValue()));
      this.showToast('Borrador guardado correctamente.', 'info', '💾');
    } catch {
      this.showToast('No se pudo guardar el borrador.', 'warning', '⚠️');
    }
  }

  private loadDraft(): void {
    const draft = this.getDraftFast();

    if (!draft) return;

    this.mainForm.patchValue(draft, { emitEvent: false });
    this.updateMirror(this.mainForm.getRawValue());
    this.showToast('Se cargó un borrador guardado.', 'info', '💾');
    this.cdr.markForCheck();
  }

  trackByIndex(index: number) {
    return index;
  }

  trackByKey(index: number, item: any) {
    return item.key;
  }

  trackByValue(index: number, item: any) {
    return item.value;
  }

  trackById(index: number, item: any) {
    return item.id;
  }

  // ─── Print / PDF ─────────────────────────────────────────────
  printMirror(): void {
    window.print();
  }

  downloadPDF(): void {
    this.showToast('Función de PDF disponible con integración de librería (jsPDF / pdfmake).', 'info', '📄');
  }

  // ─── Toasts ─────────────────────────────────────────────────
  showToast(message: string, type: ToastMessage['type'], icon: string): void {
    const id = ++this.toastCounter;
    const icons: Record<ToastMessage['type'], string> = {
      success: '✅',
      error: '❌',
      warning: '⚠️',
      info: 'ℹ️',
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