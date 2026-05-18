import { Component, OnInit, ChangeDetectorRef } from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { RouterModule } from '@angular/router';
import { catchError, finalize, of, timeout } from 'rxjs';
import Swal from 'sweetalert2';
import { FormulariosService } from '../../core/services/formularios';

@Component({
  selector: 'app-formularios',
  standalone: true,
  imports: [CommonModule, FormsModule, RouterModule],
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

  rolesValidos = [
    'Talento Humano - Recepcion Documentos',
    'Ex Funcionario',
    'Administrativa',
    'Financiera',
    'TICs',
    'Seguridad'
  ];

  asignacion = {
    usuario_id: '',
    rol: ''
  };

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

    { id: 'info_fin_resp', etiqueta: 'Responsable Informe Fin Gestión', seccion: 'Responsables', tipo: 'TEXTO', seleccionado: false },
    { id: 'bienes_resp', etiqueta: 'Responsable Bienes', seccion: 'Responsables', tipo: 'TEXTO', seleccionado: false },
    { id: 'tic_equipo_resp', etiqueta: 'Responsable TIC', seccion: 'Responsables', tipo: 'TEXTO', seleccionado: false },
    { id: 'fin_saldos_resp', etiqueta: 'Responsable Financiero', seccion: 'Responsables', tipo: 'TEXTO', seleccionado: false },
    { id: 'seg_resp', etiqueta: 'Responsable Seguridad', seccion: 'Responsables', tipo: 'TEXTO', seleccionado: false },
    { id: 'rh_cursos_resp', etiqueta: 'Responsable Talento Humano', seccion: 'Responsables', tipo: 'TEXTO', seleccionado: false }
  ];

  camposAsignadosUsuario: string[] = [];

  formulario: any = {
    nombres_apellidos: '',
    modalidad: '',
    cedula: '',
    fecha_ingreso: '',
    direccion: '',
    fecha_salida: '',
    celular: '',
    emergencia: '',
    email1: '',
    email2: '',
    provincia: '',
    canton: '',
    lugar_trabajo: '',
    unidad: '',
    cargo: '',
    grupo_ocupacional: '',
    info_fin_resp: '',
    bienes_resp: '',
    tic_equipo_resp: '',
    fin_saldos_resp: '',
    seg_resp: '',
    rh_cursos_resp: ''
  };

  nuevoFormulario = {
    titulo: '',
    descripcion: ''
  };

  constructor(
    private formulariosService: FormulariosService,
    private cdr: ChangeDetectorRef
  ) {}

  ngOnInit(): void {
    this.usuario = JSON.parse(localStorage.getItem('usuario') || '{}');

    this.cargarFormularios();
    this.cargarNotificaciones();

    if (this.esAdmin()) {
      this.cargarUsuariosDisponibles();
    } else {
      this.cargarPendientes();
    }
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

  soloLetras(texto: string): boolean {
    return /^[a-zA-ZÁÉÍÓÚáéíóúÑñ\s]+$/.test(texto || '');
  }

  validarEmail(email: string): boolean {
    return /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email || '');
  }

  validarCedula(cedula: string): boolean {
    return /^[0-9]{10}$/.test(cedula || '');
  }

  validarCelular(celular: string): boolean {
    return /^[0-9]{10}$/.test(celular || '');
  }

  validarFechas(): boolean {
    if (!this.formulario.fecha_ingreso || !this.formulario.fecha_salida) return false;

    const ingreso = new Date(this.formulario.fecha_ingreso);
    const salida = new Date(this.formulario.fecha_salida);

    return salida >= ingreso;
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

      this.nuevoFormulario = {
        titulo: '',
        descripcion: ''
      };

      this.cargarFormularios();
    });
  }

  verFormulario(f: any): void {
    this.formularioSeleccionado = f;
    this.cargarDetalleFormulario(f);
  }

  cargarDetalleFormulario(f: any): void {
    this.cargando = true;

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

      preguntas.forEach((p: any) => {
        const codigoCampo = p.codigo || p.campo || p.pregunta;

        if (codigoCampo && this.formulario.hasOwnProperty(codigoCampo)) {
          this.camposAsignadosUsuario.push(codigoCampo);

          if (p.respuesta) {
            this.formulario[codigoCampo] = p.respuesta;
          }
        }
      });

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

    if (!this.asignacion.usuario_id && !this.asignacion.rol) {
      this.alertaRapida('Validación', 'Seleccione usuario o rol destino.');
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
      usuario_id: this.asignacion.usuario_id || null,
      rol: this.asignacion.rol || null
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

      this.asignacion = {
        usuario_id: '',
        rol: ''
      };

      this.limpiarSeleccionCampos();
      this.cargarDetalleFormulario(this.formularioSeleccionado);
    });
  }

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

    const valor = this.limpiarTexto(this.formulario[campo]);

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
    const f = this.formulario;

    f.nombres_apellidos = this.limpiarTexto(f.nombres_apellidos);
    f.direccion = this.limpiarTexto(f.direccion);
    f.provincia = this.limpiarTexto(f.provincia);
    f.canton = this.limpiarTexto(f.canton);
    f.unidad = this.limpiarTexto(f.unidad);
    f.cargo = this.limpiarTexto(f.cargo);
    f.grupo_ocupacional = this.limpiarTexto(f.grupo_ocupacional);

    if (!f.nombres_apellidos || !this.soloLetras(f.nombres_apellidos)) {
      this.alertaRapida('Validación', 'Ingrese nombres y apellidos válidos.');
      return false;
    }

    if (!f.modalidad) {
      this.alertaRapida('Validación', 'Seleccione modalidad laboral.');
      return false;
    }

    if (!this.validarCedula(f.cedula)) {
      this.alertaRapida('Validación', 'La cédula debe tener 10 números.');
      return false;
    }

    if (!f.fecha_ingreso || !f.fecha_salida) {
      this.alertaRapida('Validación', 'Ingrese fecha de ingreso y salida.');
      return false;
    }

    if (!this.validarFechas()) {
      this.alertaRapida('Validación', 'La fecha de salida no puede ser menor a la fecha de ingreso.');
      return false;
    }

    if (!f.direccion || f.direccion.length < 5) {
      this.alertaRapida('Validación', 'Ingrese una dirección válida.');
      return false;
    }

    if (!this.validarCelular(f.celular)) {
      this.alertaRapida('Validación', 'El celular debe tener 10 números.');
      return false;
    }

    if (f.emergencia && !this.validarCelular(f.emergencia)) {
      this.alertaRapida('Validación', 'El contacto de emergencia debe tener 10 números.');
      return false;
    }

    if (!this.validarEmail(f.email1)) {
      this.alertaRapida('Validación', 'Ingrese un Email 1 válido.');
      return false;
    }

    if (f.email2 && !this.validarEmail(f.email2)) {
      this.alertaRapida('Validación', 'Ingrese un Email 2 válido.');
      return false;
    }

    if (!f.provincia || !this.soloLetras(f.provincia)) {
      this.alertaRapida('Validación', 'Ingrese una provincia válida.');
      return false;
    }

    if (!f.canton || !this.soloLetras(f.canton)) {
      this.alertaRapida('Validación', 'Ingrese un cantón válido.');
      return false;
    }

    if (!f.lugar_trabajo) {
      this.alertaRapida('Validación', 'Seleccione lugar de trabajo.');
      return false;
    }

    if (!f.unidad || f.unidad.length < 3) {
      this.alertaRapida('Validación', 'Ingrese dirección/unidad válida.');
      return false;
    }

    if (!f.cargo || f.cargo.length < 3) {
      this.alertaRapida('Validación', 'Ingrese cargo válido.');
      return false;
    }

    if (!f.grupo_ocupacional || f.grupo_ocupacional.length < 3) {
      this.alertaRapida('Validación', 'Ingrese grupo ocupacional válido.');
      return false;
    }

    return true;
  }

  validarYActualizarEspejo(): void {
    if (!this.validarPazSalvo()) return;

    Swal.fire({
      icon: 'success',
      title: 'Formulario válido',
      text: 'La hoja espejo fue actualizada correctamente.',
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