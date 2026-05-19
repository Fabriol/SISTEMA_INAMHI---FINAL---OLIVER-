import { Component, OnInit, ChangeDetectorRef } from '@angular/core';
import { CommonModule } from '@angular/common';
import {
  FormsModule,
  ReactiveFormsModule,
  FormBuilder,
  FormGroup,
  Validators,
  AbstractControl
} from '@angular/forms';
import { RouterModule } from '@angular/router';
import { catchError, finalize, of, timeout } from 'rxjs';
import Swal from 'sweetalert2';
import { FormulariosService } from '../../core/services/formularios';

@Component({
  selector: 'app-formularios',
  standalone: true,
  imports: [CommonModule, FormsModule, ReactiveFormsModule, RouterModule],
  templateUrl: './formularios.html',
  styleUrl: './formularios.scss'
})
export class Formularios implements OnInit {

  formularios: any[] = [];
  formularioSeleccionado: any = null;
  usuariosDisponibles: any[] = [];
  notificaciones: any[] = [];
  pendientes: any[] = [];

  usuario: any = {};
  cargando = false;
  private alertaActiva = false;

  asignacion = { usuario_id: '' };

  // =========================================================
  // TODOS LOS CAMPOS DEL FORMULARIO PAZ Y SALVO (COMPLETO)
  // =========================================================
  camposFormulario: any[] = [
    // 1. Datos Personales
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
    { id: 'provincia', etiqueta: 'Provincia', seccion: 'Datos Personales', tipo: 'TEXTO', seleccionado: false },
    { id: 'canton', etiqueta: 'Cantón', seccion: 'Datos Personales', tipo: 'TEXTO', seleccionado: false },

    // 2. Dirección / Unidad
    { id: 'lugar_trabajo', etiqueta: 'Lugar de Trabajo', seccion: 'Dirección / Unidad', tipo: 'SELECT', seleccionado: false },
    { id: 'unidad', etiqueta: 'Dirección / Unidad', seccion: 'Dirección / Unidad', tipo: 'TEXTO', seleccionado: false },
    { id: 'cargo', etiqueta: 'Cargo Desempeñado', seccion: 'Dirección / Unidad', tipo: 'TEXTO', seleccionado: false },
    { id: 'grupo_ocupacional', etiqueta: 'Grupo Ocupacional', seccion: 'Dirección / Unidad', tipo: 'TEXTO', seleccionado: false },

    // 3. Trámites y Unidad
    { id: 'tramites_informe', etiqueta: 'Entrega informe de fin de gestión', seccion: 'Trámites y Unidad', tipo: 'SELECT', seleccionado: false },
    { id: 'tramites_admin_contrato', etiqueta: '¿Es Administrador de Contrato?', seccion: 'Trámites y Unidad', tipo: 'SELECT', seleccionado: false },
    { id: 'tramites_desc_contrato', etiqueta: 'Descripción del contrato', seccion: 'Trámites y Unidad', tipo: 'TEXTO', seleccionado: false },
    { id: 'tramites_memo', etiqueta: 'Número Memorando', seccion: 'Trámites y Unidad', tipo: 'TEXTO', seleccionado: false },
    { id: 'tramites_jefe_inmediato', etiqueta: 'Nombre del Jefe Inmediato', seccion: 'Trámites y Unidad', tipo: 'TEXTO', seleccionado: false },
    { id: 'tramites_quipux_cero', etiqueta: 'Trámites Quipux / Claves', seccion: 'Trámites y Unidad', tipo: 'SELECT', seleccionado: false },
    { id: 'tramites_servidor_recibe', etiqueta: 'Servidor que recibe trámites', seccion: 'Trámites y Unidad', tipo: 'TEXTO', seleccionado: false },

    // 4. Gestión Administrativa
    { id: 'admin_informe', etiqueta: 'Entrega informe administrativo', seccion: 'Gestión Administrativa', tipo: 'SELECT', seleccionado: false },
    { id: 'admin_bienes', etiqueta: 'Entregó bienes y muebles', seccion: 'Gestión Administrativa', tipo: 'SELECT', seleccionado: false },
    { id: 'admin_acta_bienes', etiqueta: 'Número de Acta', seccion: 'Gestión Administrativa', tipo: 'TEXTO', seleccionado: false },
    { id: 'admin_valor_bienes', etiqueta: 'Valor Bienes', seccion: 'Gestión Administrativa', tipo: 'TEXTO', seleccionado: false },
    { id: 'admin_deducibles', etiqueta: '¿Tiene Deducibles?', seccion: 'Gestión Administrativa', tipo: 'SELECT', seleccionado: false },
    { id: 'admin_deducibles_valor', etiqueta: 'Valor Deducibles', seccion: 'Gestión Administrativa', tipo: 'TEXTO', seleccionado: false },
    { id: 'admin_pasajes', etiqueta: 'Pasajes aéreos', seccion: 'Gestión Administrativa', tipo: 'SELECT', seleccionado: false },
    { id: 'admin_responsable', etiqueta: 'Responsable', seccion: 'Gestión Administrativa', tipo: 'TEXTO', seleccionado: false },

    // 5. TIC
    { id: 'tic_verificacion', etiqueta: 'Verificación Equipo / Accesos', seccion: 'Gestión TIC', tipo: 'SELECT', seleccionado: false },
    { id: 'tic_backup', etiqueta: 'Entrega Backup', seccion: 'Gestión TIC', tipo: 'SELECT', seleccionado: false },
    { id: 'tic_ruta_backup', etiqueta: 'Ruta Backup', seccion: 'Gestión TIC', tipo: 'TEXTO', seleccionado: false },
    { id: 'tic_tarjeta_cuentas', etiqueta: 'Entrega Tarjeta / Cuentas', seccion: 'Gestión TIC', tipo: 'SELECT', seleccionado: false },
    { id: 'tic_responsable', etiqueta: 'Responsable TIC', seccion: 'Gestión TIC', tipo: 'TEXTO', seleccionado: false },

    // 6. Financiero
    { id: 'fin_saldos', etiqueta: 'Valores pendientes (Saldos)', seccion: 'Gestión Financiera', tipo: 'SELECT', seleccionado: false },
    { id: 'fin_recuperacion', etiqueta: 'Valores pendientes (Recuperación)', seccion: 'Gestión Financiera', tipo: 'SELECT', seleccionado: false },
    { id: 'fin_director', etiqueta: 'Director/a Financiero/a', seccion: 'Gestión Financiera', tipo: 'TEXTO', seleccionado: false },

    // 7. Seguridad
    { id: 'seg_archivos', etiqueta: 'Archivos / Info Institucional', seccion: 'Seguridad', tipo: 'SELECT', seleccionado: false },
    { id: 'seg_oficial', etiqueta: 'Oficial de Seguridad', seccion: 'Seguridad', tipo: 'TEXTO', seleccionado: false },
    { id: 'seg_responsable', etiqueta: 'Responsable Seguridad', seccion: 'Seguridad', tipo: 'TEXTO', seleccionado: false },

    // 8. RRHH
    { id: 'rrhh_cursos_eval', etiqueta: 'Cursos / Evaluación', seccion: 'Recursos Humanos', tipo: 'SELECT', seleccionado: false },
    { id: 'rrhh_vacaciones', etiqueta: 'Días Vacaciones', seccion: 'Recursos Humanos', tipo: 'TEXTO', seleccionado: false },
    { id: 'rrhh_juramentada', etiqueta: 'Constancia Juramentada', seccion: 'Recursos Humanos', tipo: 'SELECT', seleccionado: false },
    { id: 'rrhh_num_certificado', etiqueta: 'Núm. Certificado', seccion: 'Recursos Humanos', tipo: 'TEXTO', seleccionado: false },
    { id: 'rrhh_num_declaracion', etiqueta: 'Núm. Declaración', seccion: 'Recursos Humanos', tipo: 'TEXTO', seleccionado: false },
    { id: 'rrhh_credencial', etiqueta: 'Credencial / Copias CD', seccion: 'Recursos Humanos', tipo: 'SELECT', seleccionado: false },
    { id: 'rrhh_director', etiqueta: 'Director/a RRHH', seccion: 'Recursos Humanos', tipo: 'TEXTO', seleccionado: false },

    // 9. Recepción
    { id: 'recepcion_fecha', etiqueta: 'Fecha de Entrega', seccion: 'Recepción', tipo: 'FECHA', seleccionado: false },
    { id: 'recepcion_hojas', etiqueta: 'Hojas Recibidas', seccion: 'Recepción', tipo: 'TEXTO', seleccionado: false },
    { id: 'recepcion_servidor', etiqueta: 'Servidor que recibe', seccion: 'Recepción', tipo: 'TEXTO', seleccionado: false },
    { id: 'recepcion_cargo', etiqueta: 'Cargo Servidor', seccion: 'Recepción', tipo: 'TEXTO', seleccionado: false }
  ];

  camposAsignadosUsuario: string[] = [];
  camposBloqueados: string[] = [];
  camposYaDesignados: string[] = [];

  nuevoFormulario = {
    titulo: '',
    descripcion: ''
  };

  formularioPazSalvo!: FormGroup;

  seccionesAbiertas: any = {
    personales: true,
    direccion: false,
    admin: false,
    tramites: false,
    tic: false,
    financiero: false,
    seguridad: false,
    rrhh: false,
    recepcion: false
  };

  constructor(
    private formulariosService: FormulariosService,
    private cdr: ChangeDetectorRef,
    private fb: FormBuilder
  ) { }

  ngOnInit(): void {
    this.usuario = JSON.parse(localStorage.getItem('usuario') || '{}');

    this.inicializarFormularioReactivo();
    this.cargarFormularios();
    this.cargarNotificaciones();

    if (this.esAdmin()) {
      this.cargarUsuariosDisponibles();
    } else {
      this.cargarPendientes();
    }
  }

  inicializarFormularioReactivo(): void {
    this.formularioPazSalvo = this.fb.group({
      // 1. Datos Personales
      nombres_apellidos: ['', [Validators.required, this.validadorLetras.bind(this)]],
      modalidad: ['', Validators.required],
      cedula: ['', [Validators.required, this.validadorCedula.bind(this)]],
      fecha_ingreso: ['', Validators.required],
      direccion: ['', [Validators.required, Validators.minLength(5)]],
      numero_domicilio: [''], 
      fecha_salida: ['', Validators.required],
      celular: ['', [Validators.required, this.validadorCelular.bind(this)]],
      emergencia: ['', [this.validadorCelular.bind(this)]], 
      email1: ['', [Validators.required, Validators.email]],
      email2: ['', [Validators.email]],
      provincia: ['', [Validators.required, this.validadorLetras.bind(this)]],
      canton: ['', [Validators.required, this.validadorLetras.bind(this)]],

      // 2. Dirección / Unidad
      lugar_trabajo: ['', Validators.required],
      unidad: ['', [Validators.required, Validators.minLength(3)]],
      cargo: ['', [Validators.required, Validators.minLength(3)]],
      grupo_ocupacional: ['', [Validators.required, Validators.minLength(3)]],

      // 3. Trámites
      tramites_informe: ['', Validators.required],
      tramites_admin_contrato: ['NO', Validators.required],
      tramites_desc_contrato: [{ value: '', disabled: true }],
      tramites_memo: [{ value: '', disabled: true }],
      tramites_jefe_inmediato: ['', Validators.required],
      tramites_quipux_cero: ['', Validators.required],
      tramites_servidor_recibe: ['', Validators.required],

      // 4. Gestión Administrativa
      admin_informe: ['', Validators.required],
      admin_bienes: ['', Validators.required],
      admin_acta_bienes: [''],
      admin_valor_bienes: [''],
      admin_deducibles: ['NO', Validators.required],
      admin_deducibles_valor: [{ value: '', disabled: true }],
      admin_pasajes: ['', Validators.required],
      admin_responsable: ['', Validators.required],

      // 5. TIC
      tic_verificacion: ['', Validators.required],
      tic_backup: ['', Validators.required],
      tic_ruta_backup: [''],
      tic_tarjeta_cuentas: ['', Validators.required],
      tic_responsable: ['', Validators.required],

      // 6. Financiero
      fin_saldos: ['', Validators.required],
      fin_recuperacion: ['', Validators.required],
      fin_director: ['', Validators.required],

      // 7. Seguridad
      seg_archivos: ['', Validators.required],
      seg_oficial: ['', Validators.required],
      seg_responsable: ['', Validators.required],

      // 8. RRHH
      rrhh_cursos_eval: ['', Validators.required],
      rrhh_vacaciones: ['', Validators.required],
      rrhh_juramentada: ['', Validators.required],
      rrhh_num_certificado: [''],
      rrhh_num_declaracion: [''],
      rrhh_credencial: ['', Validators.required],
      rrhh_director: ['', Validators.required],

      // 9. Recepción
      recepcion_fecha: ['', Validators.required],
      recepcion_hojas: ['', Validators.required],
      recepcion_servidor: ['', Validators.required],
      recepcion_cargo: ['', Validators.required],

    }, { validators: this.validadorFechasGrupo.bind(this) });

    // Dinamismo: Deducibles
    this.formularioPazSalvo.get('admin_deducibles')?.valueChanges.subscribe(val => {
      const campoValor = this.formularioPazSalvo.get('admin_deducibles_valor');
      if (val === 'SI') {
        campoValor?.enable();
        campoValor?.setValidators([Validators.required, Validators.min(0.01)]);
      } else {
        campoValor?.disable();
        campoValor?.clearValidators();
        campoValor?.setValue('');
      }
      campoValor?.updateValueAndValidity();
    });

    // Dinamismo: Administrador de Contratos
    this.formularioPazSalvo.get('tramites_admin_contrato')?.valueChanges.subscribe(val => {
      const desc = this.formularioPazSalvo.get('tramites_desc_contrato');
      const memo = this.formularioPazSalvo.get('tramites_memo');
      if (val === 'SI') {
        desc?.enable();
        memo?.enable();
        desc?.setValidators([Validators.required, Validators.minLength(3)]);
        memo?.setValidators([Validators.required]);
      } else {
        desc?.disable();
        memo?.disable();
        desc?.clearValidators();
        memo?.clearValidators();
        desc?.setValue('');
        memo?.setValue('');
      }
      desc?.updateValueAndValidity();
      memo?.updateValueAndValidity();
    });
  }

  validadorLetras(control: AbstractControl): { [key: string]: boolean } | null {
    if (!control.value) return null;
    return /^[a-zA-ZÁÉÍÓÚáéíóúÑñ\s]+$/.test(control.value)
      ? null
      : { soloLetras: true };
  }

  validadorCedula(control: AbstractControl): { [key: string]: boolean } | null {
    if (!control.value) return null;
    return /^[a-zA-Z0-9]{10,15}$/.test(control.value) // Ampliado para aceptar pasaportes
      ? null
      : { cedulaInvalida: true };
  }

  validadorCelular(control: AbstractControl): { [key: string]: boolean } | null {
    if (!control.value) return null;
    return /^[0-9]{10}$/.test(control.value)
      ? null
      : { celularInvalido: true };
  }

  validadorFechasGrupo(group: AbstractControl): { [key: string]: boolean } | null {
    const ingreso = group.get('fecha_ingreso')?.value;
    const salida = group.get('fecha_salida')?.value;

    if (ingreso && salida) {
      return new Date(salida) >= new Date(ingreso)
        ? null
        : { fechasInvalidas: true };
    }
    return null;
  }

  esAdmin(): boolean {
    return this.usuario?.rol === 'Administrador';
  }

  limpiarTexto(texto: any): string {
    return String(texto || '').trim().replace(/\s+/g, ' ');
  }

  alertaRapida(titulo: string, texto: string): void {
    if (this.alertaActiva) return;

    this.alertaActiva = true;

    Swal.fire({
      icon: 'warning',
      title: titulo,
      text: texto,
      timer: 1800,
      showConfirmButton: false
    }).then(() => this.alertaActiva = false);
  }

  validarFormulario(): boolean {
    this.nuevoFormulario.titulo = this.limpiarTexto(this.nuevoFormulario.titulo);
    this.nuevoFormulario.descripcion = this.limpiarTexto(this.nuevoFormulario.descripcion);

    if (!this.nuevoFormulario.titulo || this.nuevoFormulario.titulo.length < 3) {
      this.alertaRapida('Validación', 'El título debe tener mínimo 3 caracteres.');
      return false;
    }
    return true;
  }

  cargarFormularios(): void {
    this.cargando = true;

    this.formulariosService.listar().pipe(
      timeout(4000),
      catchError((err: any) => {
        Swal.fire('Error', err.error?.mensaje || 'Error al cargar formularios', 'error');
        return of([]);
      }),
      finalize(() => {
        this.cargando = false;
        this.cdr.detectChanges();
      })
    ).subscribe((data: any[]) => {
      this.formularios = data || [];
    });
  }

  crearFormulario(): void {
    if (!this.esAdmin()) {
      this.alertaRapida('Sin permisos', 'Solo el Administrador puede crear formularios.');
      return;
    }

    const data = {
      titulo: 'PAZ Y SALVO',
      descripcion: 'Formulario oficial de Paz y Salvo'
    };

    this.cargando = true;

    this.formulariosService.crear(data).pipe(
      timeout(4000),
      catchError((err: any) => {
        Swal.fire('Error', err.error?.mensaje || 'Error al crear formulario', 'error');
        return of(null);
      }),
      finalize(() => {
        this.cargando = false;
        this.cdr.detectChanges();
      })
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
    this.formularioPazSalvo.reset({ admin_deducibles: 'NO', tramites_admin_contrato: 'NO' });
    this.camposAsignadosUsuario = [];
    this.camposBloqueados = [];
    this.camposYaDesignados = [];
    
    this.camposFormulario.forEach(c => {
      c.bloqueado = false;
      c.seleccionado = false;
    });

    this.formulariosService.ver(f.id).pipe(
      timeout(4000),
      catchError((err: any) => {
        Swal.fire('Error', err.error?.mensaje || 'No se pudo cargar formulario', 'error');
        return of(null);
      }),
      finalize(() => {
        this.cargando = false;
        this.cdr.detectChanges();
      })
    ).subscribe((data: any) => {
      if (!data) return;

      this.formularioSeleccionado = data.formulario;
      const preguntas = data.preguntas || [];
      const valores: any = {};

      preguntas.forEach((p: any) => {
        const campo = p.codigo || p.campo || p.pregunta;

        if (campo && this.formularioPazSalvo.controls[campo]) {
          this.camposAsignadosUsuario.push(campo);

          if (p.respuesta) {
            valores[campo] = p.respuesta;
            this.camposBloqueados.push(campo);
          }

          if (p.ya_asignado === 1 || p.asignacion_id) {
            this.camposYaDesignados.push(campo);
          }
        }
      });

      this.camposYaDesignados = [...new Set(this.camposYaDesignados)];

      this.camposFormulario.forEach(c => {
        c.bloqueado = this.camposYaDesignados.includes(c.id);
        if (c.bloqueado) c.seleccionado = false;
      });

      this.camposAsignadosUsuario = [...new Set(this.camposAsignadosUsuario)];
      this.camposBloqueados = [...new Set(this.camposBloqueados)];

      this.formularioPazSalvo.patchValue(valores);
      this.bloquearCamposNoPermitidos();
      this.cdr.detectChanges();
    });
  }

  bloquearCamposNoPermitidos(): void {
    Object.keys(this.formularioPazSalvo.controls).forEach(campo => {
      const control = this.formularioPazSalvo.get(campo);

      if (this.esAdmin()) {
        control?.enable({ emitEvent: false });
        return;
      }

      if (!this.camposAsignadosUsuario.includes(campo) || this.camposBloqueados.includes(campo)) {
        control?.disable({ emitEvent: false });
      } else {
        control?.enable({ emitEvent: false });
      }
    });
  }

  cargarUsuariosDisponibles(): void {
    this.formulariosService.usuariosDisponibles().pipe(
      timeout(4000),
      catchError(() => of([]))
    ).subscribe((data: any[]) => {
      this.usuariosDisponibles = data || [];
    });
  }

  cargarPendientes(): void {
    this.formulariosService.misPendientes().pipe(
      catchError(() => of([]))
    ).subscribe((data: any[]) => {
      this.pendientes = data || [];
    });
  }

  cargarNotificaciones(): void {
    this.formulariosService.notificaciones().pipe(
      catchError(() => of([]))
    ).subscribe((data: any[]) => {
      this.notificaciones = data || [];
    });
  }

  marcarNotificacionLeida(n: any): void {
    this.formulariosService.marcarNotificacionLeida(n.id).subscribe(() => {
      n.leido = 1;
    });
  }

  camposSeleccionados(): any[] {
    return this.camposFormulario.filter(c => c.seleccionado && !c.bloqueado);
  }

  seleccionarTodosCampos(): void {
    this.camposFormulario.forEach(c => {
      if (!c.bloqueado) c.seleccionado = true;
    });
  }

  limpiarSeleccionCampos(): void {
    this.camposFormulario.forEach(c => c.seleccionado = false);
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
      campos: seleccionados.map(c => ({
        codigo: c.id,
        pregunta: c.etiqueta,
        seccion: c.seccion,
        tipo: c.tipo
      })),
      usuario_id: this.asignacion.usuario_id,
      rol: null
    };

    this.cargando = true;

    this.formulariosService.asignar(data).pipe(
      timeout(4000),
      catchError((err: any) => {
        Swal.fire('Error', err.error?.mensaje || err.error?.error || 'Error al designar campos', 'error');
        return of(null);
      }),
      finalize(() => {
        this.cargando = false;
        this.cdr.detectChanges();
      })
    ).subscribe((res: any) => {
      if (!res) return;

      Swal.fire('Enviado', res.mensaje || 'Campos designados correctamente.', 'success');
      this.asignacion = { usuario_id: '' };
      this.limpiarSeleccionCampos();
      this.cargarDetalleFormulario(this.formularioSeleccionado);
    });
  }

  puedeEditarCampo(campo: string): boolean {
    if (this.esAdmin()) return true;
    return this.camposAsignadosUsuario.includes(campo) && !this.camposBloqueados.includes(campo);
  }

  validarPazSalvo(): boolean {
    if (this.esAdmin()) {
      if (this.formularioPazSalvo.invalid) {
        this.formularioPazSalvo.markAllAsTouched();
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
      const control = this.formularioPazSalvo.get(campo);
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

  guardarCamposAsignados(): void {
    const campos = this.camposAsignadosUsuario.filter(campo => {
      const control = this.formularioPazSalvo.get(campo);
      return !this.camposBloqueados.includes(campo) && control && this.limpiarTexto(control.value) !== '';
    });

    if (campos.length === 0) {
      this.alertaRapida('Validación', 'No hay campos nuevos para guardar.');
      return;
    }

    let guardados = 0;

    campos.forEach(campo => {
      const control = this.formularioPazSalvo.get(campo);

      this.formulariosService.responder({
        formulario_id: this.formularioSeleccionado.id,
        campo,
        respuesta: this.limpiarTexto(control?.value)
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
          console.error('ERROR BACKEND:', err);
          Swal.fire('Error', err?.error?.mensaje || err?.error?.error || 'Error al guardar campos', 'error');
        }
      });
    });
  }

  toggleSeccion(key: string) {
    this.seccionesAbiertas[key] = !this.seccionesAbiertas[key];
  }

  isOpen(key: string): boolean {
    return this.seccionesAbiertas[key];
  }

  async exportarHojaEspejoPDF(): Promise<void> {
    if (!this.formularioSeleccionado?.id) return;

    const html2canvas = (await import('html2canvas')).default;
    const jsPDF = (await import('jspdf')).default;

    const element = document.querySelector('.a4-page') as HTMLElement;

    if (!element) {
      Swal.fire('Error', 'No se encontró el documento A4', 'error');
      return;
    }

    const canvas = await html2canvas(element, {
      scale: 2,
      useCORS: true,
      backgroundColor: '#ffffff'
    });

    const imgData = canvas.toDataURL('image/png');
    const pdf = new jsPDF('p', 'mm', 'a4');

    const imgWidth = 210;
    const imgHeight = (canvas.height * imgWidth) / canvas.width;

    pdf.addImage(imgData, 'PNG', 0, 0, imgWidth, imgHeight);

    pdf.save('formulario-paz-y-salvo.pdf');
  }

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
      cancelButtonText: 'Cancelar'
    }).then(result => {
      if (!result.isConfirmed) return;

      this.cargando = true;

      this.formulariosService.eliminar(f.id).pipe(
        timeout(4000),
        catchError((err: any) => {
          Swal.fire('Error', err.error?.mensaje || 'Error al eliminar formulario', 'error');
          return of(null);
        }),
        finalize(() => {
          this.cargando = false;
          this.cdr.detectChanges();
        })
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

  descargarPDF(): void {
    if (!this.formularioSeleccionado?.id) {
      this.alertaRapida('Validación', 'Seleccione un formulario primero.');
      return;
    }

    window.open(`http://localhost:5000/api/formularios/${this.formularioSeleccionado.id}/pdf`, '_blank');
  }
}