import { Component, OnInit, ChangeDetectorRef } from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormsModule, ReactiveFormsModule, FormBuilder, FormGroup, Validators, AbstractControl } from '@angular/forms';
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

  camposFormulario: any[] = [
    { id: 'nombres_apellidos', etiqueta: 'Nombres y Apellidos', seccion: 'Datos Personales', tipo: 'TEXTO', seleccionado: false },
    { id: 'modalidad', etiqueta: 'Modalidad Laboral', seccion: 'Datos Personales', tipo: 'SELECT', seleccionado: false },
    { id: 'cedula', etiqueta: 'Cédula / Pasaporte', seccion: 'Datos Personales', tipo: 'TEXTO', seleccionado: false },
    { id: 'fecha_ingreso', etiqueta: 'Fecha de Ingreso', seccion: 'Datos Personales', tipo: 'FECHA', seleccionado: false },
    { id: 'direccion', etiqueta: 'Dirección Domiciliaria', seccion: 'Datos Personales', tipo: 'TEXTO', seleccionado: false },
    { id: 'fecha_salida', etiqueta: 'Fecha de Salida', seccion: 'Datos Personales', tipo: 'FECHA', seleccionado: false },
    { id: 'celular', etiqueta: 'Número Celular', seccion: 'Datos Personales', tipo: 'TEXTO', seleccionado: false },
    { id: 'emergencia', etiqueta: 'Contacto Emergencia', seccion: 'Datos Personales', tipo: 'TEXTO', seleccionado: false },
    { id: 'email1', etiqueta: 'Email 1', seccion: 'Datos Personales', tipo: 'TEXTO', seleccionado: false },
    { id: 'email2', etiqueta: 'Email 2', seccion: 'Datos Personales', tipo: 'TEXTO', seleccionado: false },
    { id: 'provincia', etiqueta: 'Provincia', seccion: 'Datos Personales', tipo: 'TEXTO', seleccionado: false },
    { id: 'canton', etiqueta: 'Cantón', seccion: 'Datos Personales', tipo: 'TEXTO', seleccionado: false },
    { id: 'lugar_trabajo', etiqueta: 'Lugar de Trabajo', seccion: 'Dirección / Unidad', tipo: 'SELECT', seleccionado: false },
    { id: 'unidad', etiqueta: 'Dirección / Unidad', seccion: 'Dirección / Unidad', tipo: 'TEXTO', seleccionado: false },
    { id: 'cargo', etiqueta: 'Cargo Desempeñado', seccion: 'Dirección / Unidad', tipo: 'TEXTO', seleccionado: false },
    { id: 'grupo_ocupacional', etiqueta: 'Grupo Ocupacional', seccion: 'Dirección / Unidad', tipo: 'TEXTO', seleccionado: false },
    { id: 'admin_deducibles', etiqueta: '¿Tiene Deducibles?', seccion: 'Gestión Administrativa', tipo: 'SELECT', seleccionado: false },
    { id: 'admin_deducibles_valor', etiqueta: 'Valor Deducibles', seccion: 'Gestión Administrativa', tipo: 'TEXTO', seleccionado: false }
  ];

  camposAsignadosUsuario: string[] = [];

  nuevoFormulario = {
    titulo: '',
    descripcion: ''
  };

  // FormGroup principal que reemplaza al objeto "formulario: any"
  formularioPazSalvo!: FormGroup;

  constructor(
    private formulariosService: FormulariosService,
    private cdr: ChangeDetectorRef,
    private fb: FormBuilder
  ) {}

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

  // ========================================================
  // INICIALIZACIÓN Y LÓGICA REACTIVA (NUEVO MOTOR)
  // ========================================================
  inicializarFormularioReactivo(): void {
    this.formularioPazSalvo = this.fb.group({
      nombres_apellidos: ['', [Validators.required, this.validadorLetras.bind(this)]],
      modalidad: ['', Validators.required],
      cedula: ['', [Validators.required, this.validadorCedula.bind(this)]],
      fecha_ingreso: ['', Validators.required],
      direccion: ['', [Validators.required, Validators.minLength(5)]],
      fecha_salida: ['', Validators.required],
      celular: ['', [Validators.required, this.validadorCelular.bind(this)]],
      emergencia: ['', [this.validadorCelular.bind(this)]], 
      email1: ['', [Validators.required, Validators.email]],
      email2: ['', [Validators.email]],
      provincia: ['', [Validators.required, this.validadorLetras.bind(this)]],
      canton: ['', [Validators.required, this.validadorLetras.bind(this)]],
      
      lugar_trabajo: ['', Validators.required],
      unidad: ['', [Validators.required, Validators.minLength(3)]],
      cargo: ['', [Validators.required, Validators.minLength(3)]],
      grupo_ocupacional: ['', [Validators.required, Validators.minLength(3)]],

      admin_deducibles: ['NO'],
      admin_deducibles_valor: [{ value: '', disabled: true }]
    }, { validators: this.validadorFechasGrupo.bind(this) });

    // Listener reactivo: Activa/Desactiva obligatoriedad dinámicamente
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
  }

  // ========================================================
  // VALIDACIONES PERSONALIZADAS (CUSTOM VALIDATORS)
  // ========================================================
  validadorLetras(control: AbstractControl): { [key: string]: boolean } | null {
    if (!control.value) return null;
    return /^[a-zA-ZÁÉÍÓÚáéíóúÑñ\s]+$/.test(control.value) ? null : { soloLetras: true };
  }

  validadorCedula(control: AbstractControl): { [key: string]: boolean } | null {
    if (!control.value) return null;
    return /^[0-9]{10}$/.test(control.value) ? null : { cedulaInvalida: true };
  }

  validadorCelular(control: AbstractControl): { [key: string]: boolean } | null {
    if (!control.value) return null;
    return /^[0-9]{10}$/.test(control.value) ? null : { celularInvalido: true };
  }

  validadorFechasGrupo(group: AbstractControl): { [key: string]: boolean } | null {
    const ingreso = group.get('fecha_ingreso')?.value;
    const salida = group.get('fecha_salida')?.value;
    if (ingreso && salida) {
      return new Date(salida) >= new Date(ingreso) ? null : { fechasInvalidas: true };
    }
    return null;
  }

  // ========================================================
  // UTILIDADES GLOBALES
  // ========================================================
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

  // ========================================================
  // LÓGICA DE NEGOCIO Y API (ADMIN / ASIGNACIÓN)
  // ========================================================
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
    if (!this.validarFormulario()) return;
    this.cargando = true;

    this.formulariosService.crear(this.nuevoFormulario).pipe(
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
      Swal.fire('Creado', 'Formulario creado correctamente.', 'success');
      this.nuevoFormulario = { titulo: '', descripcion: '' };
      this.cargarFormularios();
    });
  }

  verFormulario(f: any): void {
    this.formularioSeleccionado = f;
    this.cargarDetalleFormulario(f);
  }

  cargarDetalleFormulario(f: any): void {
    this.cargando = true;
    this.formularioPazSalvo.reset({ admin_deducibles: 'NO' }); // Limpiar estado previo

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
      this.camposAsignadosUsuario = [];
      const preguntas = data.preguntas || [];
      const parchesDeValores: any = {};

      preguntas.forEach((p: any) => {
        const codigoCampo = p.codigo || p.campo || p.pregunta;
        if (codigoCampo && this.formularioPazSalvo.controls.hasOwnProperty(codigoCampo)) {
          this.camposAsignadosUsuario.push(codigoCampo);
          if (p.respuesta) {
            parchesDeValores[codigoCampo] = p.respuesta;
          }
        }
      });

      // Mapeo automático de backend hacia FormGroup
      this.formularioPazSalvo.patchValue(parchesDeValores);
      this.cdr.detectChanges();
    });
  }

  cargarUsuariosDisponibles(): void {
    this.formulariosService.usuariosDisponibles().pipe(
      timeout(4000),
      catchError((err: any) => {
        Swal.fire('Error', err.error?.mensaje || 'No se pudieron cargar usuarios.', 'error');
        return of([]);
      })
    ).subscribe((data: any[]) => {
      this.usuariosDisponibles = data || [];
      this.cdr.detectChanges();
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
      const noLeidas = this.notificaciones.filter(n => !n.leido);
      if (noLeidas.length > 0) {
        Swal.fire({
          icon: 'info',
          title: 'Notificación',
          text: noLeidas[0].mensaje,
          timer: 2500,
          showConfirmButton: false
        });
      }
    });
  }

  marcarNotificacionLeida(n: any): void {
    this.formulariosService.marcarNotificacionLeida(n.id).subscribe(() => {
      n.leido = 1;
    });
  }

  camposSeleccionados(): any[] {
    return this.camposFormulario.filter(c => c.seleccionado);
  }

  seleccionarTodosCampos(): void {
    this.camposFormulario.forEach(c => c.seleccionado = true);
  }

  limpiarSeleccionCampos(): void {
    this.camposFormulario.forEach(c => c.seleccionado = false);
  }

  designarCampos(): void {
    if (!this.esAdmin()) {
      this.alertaRapida('Sin permisos', 'Solo el Administrador puede designar campos.');
      return;
    }
    if (!this.formularioSeleccionado?.id) {
      this.alertaRapida('Validación', 'Seleccione un formulario primero.');
      return;
    }
    const seleccionados = this.camposSeleccionados();
    if (seleccionados.length === 0) {
      this.alertaRapida('Validación', 'Seleccione al menos un campo del formulario.');
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
        Swal.fire('Error', err.error?.mensaje || 'Error al designar campos', 'error');
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

  // ========================================================
  // GUARDADO DE CAMPOS REACTIVOS Y EXPORTACIÓN PDF
  // ========================================================
  puedeEditarCampo(campo: string): boolean {
    if (this.esAdmin()) return true;
    return this.camposAsignadosUsuario.includes(campo);
  }

  guardarCampo(campo: string): void {
    if (!this.formularioSeleccionado?.id) {
      this.alertaRapida('Validación', 'Seleccione un formulario primero.');
      return;
    }
    if (!this.puedeEditarCampo(campo)) {
      this.alertaRapida('Sin permisos', 'No puede llenar este campo.');
      return;
    }

    const control = this.formularioPazSalvo.get(campo);
    if (control?.invalid) {
      this.alertaRapida('Validación', 'El formato del campo no es válido o está incompleto.');
      return;
    }

    const valor = this.limpiarTexto(control?.value);
    if (!valor) {
      this.alertaRapida('Validación', 'Ingrese un valor antes de guardar.');
      return;
    }

    const data = {
      formulario_id: this.formularioSeleccionado.id,
      campo,
      respuesta: valor
    };

    this.formulariosService.responder(data).subscribe({
      next: () => {
        Swal.fire('Guardado', 'Campo guardado correctamente.', 'success');
        this.cargarDetalleFormulario(this.formularioSeleccionado);
        this.cargarPendientes();
      },
      error: (err) => {
        Swal.fire('Error', err.error?.mensaje || 'Error al guardar campo', 'error');
      }
    });
  }

  validarPazSalvo(): boolean {
    // La nueva validación reactiva es en una sola línea
    if (this.formularioPazSalvo.invalid) {
      this.formularioPazSalvo.markAllAsTouched();
      this.alertaRapida('Validación', 'Por favor, revise y complete correctamente todos los campos marcados en rojo.');
      return false;
    }
    
    // Validar error custom de fechas
    if (this.formularioPazSalvo.hasError('fechasInvalidas')) {
      this.alertaRapida('Validación', 'La fecha de salida no puede ser menor a la fecha de ingreso.');
      return false;
    }

    return true;
  }

  validarYActualizarEspejo(): void {
    if (!this.validarPazSalvo()) return;

    Swal.fire({
      icon: 'success',
      title: 'Formulario válido',
      text: 'La hoja espejo está lista y sincronizada correctamente.',
      timer: 1600,
      showConfirmButton: false
    });
  }

  async exportarHojaEspejoPDF(): Promise<void> {
    if (!this.validarPazSalvo()) return;

    const html2canvas = (await import('html2canvas')).default;
    const jsPDF = (await import('jspdf')).default;

    const element = document.getElementById('hojaEspejo');
    if (!element) {
      Swal.fire('Error', 'No se encontró la hoja espejo', 'error');
      return;
    }

    const canvas = await html2canvas(element, {
      scale: 2,
      useCORS: true,
      backgroundColor: '#ffffff'
    });

    const imgData = canvas.toDataURL('image/png');
    const pdf = new jsPDF('p', 'mm', 'a4');

    const pdfWidth = 210;
    const pdfHeight = 297;
    const imgHeight = (canvas.height * pdfWidth) / canvas.width;

    let heightLeft = imgHeight;
    let position = 0;

    pdf.addImage(imgData, 'PNG', 0, position, pdfWidth, imgHeight);
    heightLeft -= pdfHeight;

    while (heightLeft > 0) {
      position = heightLeft - imgHeight;
      pdf.addPage();
      pdf.addImage(imgData, 'PNG', 0, position, pdfWidth, imgHeight);
      heightLeft -= pdfHeight;
    }

    pdf.save('formulario-paz-y-salvo.pdf');
  }

  descargarPDF(): void {
    if (!this.formularioSeleccionado?.id) {
      this.alertaRapida('Validación', 'Seleccione un formulario primero.');
      return;
    }
    window.open(`http://localhost:5000/api/formularios/${this.formularioSeleccionado.id}/pdf`, '_blank');
  }
}