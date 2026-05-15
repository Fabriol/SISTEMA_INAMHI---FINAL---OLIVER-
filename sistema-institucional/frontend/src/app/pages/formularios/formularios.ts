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
  preguntas: any[] = [];

  usuario: any = {};
  cargando = false;
  error = '';

  formData: any = {
    nombres: '',
    cedula: '',
    celular: '',
    correo: '',
    domicilio: '',
    provincia: '',
    canton: '',
    modalidad: '',
    fechaIngreso: '',
    fechaSalida: '',
    lugarTrabajo: '',
    direccionUnidad: '',
    cargo: '',
    grupoOcupacional: '',
    observaciones: ''
  };

  nuevoFormulario = {
    titulo: '',
    descripcion: ''
  };

  nuevaPregunta: any = {
    pregunta: '',
    tipo: 'TEXTO',
    opciones: ''
  };

  respuestas: any = {};
  private alertaActiva = false;

  constructor(
    private formulariosService: FormulariosService,
    private cdr: ChangeDetectorRef
  ) {}

  ngOnInit(): void {
    this.usuario = JSON.parse(localStorage.getItem('usuario') || '{}');
    this.cargarFormularios();
  }

  esAdmin(): boolean {
    return this.usuario?.rol === 'Administrador';
  }

  puedeResponder(p: any): boolean {
    if (this.formularioSeleccionado?.estado === 'COMPLETADO') return false;
    if (this.esAdmin()) return true;
    if (!p.asignacion_id) return false;
    if (p.asignado_usuario_id == this.usuario?.id) return true;
    if (p.asignado_rol == this.usuario?.rol) return true;
    return false;
  }

  limpiarTexto(texto: string): string {
    return (texto || '').trim().replace(/\s+/g, ' ');
  }

  alertaRapida(titulo: string, texto: string): void {
    if (this.alertaActiva) return;

    this.alertaActiva = true;

    Swal.fire({
      icon: 'warning',
      title: titulo,
      text: texto,
      timer: 1500,
      showConfirmButton: false
    }).then(() => {
      this.alertaActiva = false;
    });
  }

  obtenerOpciones(opciones: any): string[] {
    if (!opciones) return [];

    if (Array.isArray(opciones)) {
      return opciones.map(o => String(o).trim()).filter(o => o);
    }

    try {
      const data = JSON.parse(opciones);
      if (Array.isArray(data)) {
        return data.map(o => String(o).trim()).filter(o => o);
      }
    } catch {}

    return String(opciones)
      .split(',')
      .map(o => o.trim().replaceAll('"', '').replaceAll('[', '').replaceAll(']', ''))
      .filter(o => o);
  }

  validarFormulario(): boolean {
    this.nuevoFormulario.titulo = this.limpiarTexto(this.nuevoFormulario.titulo);
    this.nuevoFormulario.descripcion = this.limpiarTexto(this.nuevoFormulario.descripcion);

    if (!this.nuevoFormulario.titulo) {
      this.alertaRapida('Validación', 'Ingrese el título del formulario.');
      return false;
    }

    if (this.nuevoFormulario.titulo.length < 3) {
      this.alertaRapida('Validación', 'El título debe tener mínimo 3 caracteres.');
      return false;
    }

    return true;
  }

  validarPregunta(): boolean {
    this.nuevaPregunta.pregunta = this.limpiarTexto(this.nuevaPregunta.pregunta);

    if (!this.nuevaPregunta.pregunta) {
      this.alertaRapida('Validación', 'Ingrese la pregunta.');
      return false;
    }

    if (this.nuevaPregunta.pregunta.length < 3) {
      this.alertaRapida('Validación', 'La pregunta debe tener mínimo 3 caracteres.');
      return false;
    }

    if (this.nuevaPregunta.tipo === 'SELECT') {
      const opciones = this.obtenerOpciones(this.nuevaPregunta.opciones);

      if (opciones.length < 2) {
        this.alertaRapida('Validación', 'Ingrese mínimo 2 opciones separadas por coma.');
        return false;
      }
    }

    return true;
  }

  cargarFormularios(): void {
    if (this.cargando) return;

    this.cargando = true;
    this.error = '';

    this.formulariosService.listar().pipe(
      timeout(4000),
      catchError((err: any) => {
        this.error = err.error?.mensaje || 'Error al cargar formularios';
        Swal.fire('Error', this.error, 'error');
        return of([]);
      }),
      finalize(() => {
        this.cargando = false;
        this.cdr.detectChanges();
      })
    ).subscribe((data: any[]) => {
      this.formularios = data || [];
      this.cdr.detectChanges();
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
      this.preguntas = data.preguntas || [];
      this.respuestas = {};

      this.preguntas.forEach((p: any) => {
        if (p.respuesta) {
          this.respuestas[p.id] = p.respuesta;
        }
      });

      this.cdr.detectChanges();
    });
  }

  agregarPregunta(): void {
    if (!this.esAdmin()) {
      this.alertaRapida('Sin permisos', 'Solo el Administrador puede agregar preguntas.');
      return;
    }

    if (!this.formularioSeleccionado?.id) {
      this.alertaRapida('Validación', 'Seleccione un formulario primero.');
      return;
    }

    if (!this.validarPregunta()) return;

    const data = {
      pregunta: this.nuevaPregunta.pregunta,
      tipo: this.nuevaPregunta.tipo,
      opciones: this.nuevaPregunta.tipo === 'SELECT'
        ? this.obtenerOpciones(this.nuevaPregunta.opciones)
        : null
    };

    this.cargando = true;

    this.formulariosService.agregarPregunta(this.formularioSeleccionado.id, data).pipe(
      timeout(4000),
      catchError((err: any) => {
        Swal.fire('Error', err.error?.mensaje || 'Error al agregar pregunta', 'error');
        return of(null);
      }),
      finalize(() => {
        this.cargando = false;
        this.cdr.detectChanges();
      })
    ).subscribe((res: any) => {
      if (!res) return;

      Swal.fire('Agregado', 'Pregunta agregada correctamente.', 'success');

      this.nuevaPregunta = {
        pregunta: '',
        tipo: 'TEXTO',
        opciones: ''
      };

      this.verFormulario(this.formularioSeleccionado);
    });
  }

  guardarRespuesta(p: any): void {
    if (!this.puedeResponder(p)) {
      this.alertaRapida('Sin permisos', 'No puede responder esta pregunta.');
      return;
    }

    const respuesta = this.respuestas[p.id];

    if (!respuesta || String(respuesta).trim() === '') {
      this.alertaRapida('Validación', 'Ingrese una respuesta.');
      return;
    }

    const data = {
      formulario_id: this.formularioSeleccionado.id,
      pregunta_id: p.id,
      asignacion_id: p.asignacion_id,
      respuesta: String(respuesta).trim()
    };

    this.cargando = true;

    this.formulariosService.responder(data).pipe(
      timeout(4000),
      catchError((err: any) => {
        Swal.fire('Error', err.error?.mensaje || 'Error al guardar respuesta', 'error');
        return of(null);
      }),
      finalize(() => {
        this.cargando = false;
        this.cdr.detectChanges();
      })
    ).subscribe((res: any) => {
      if (!res) return;

      Swal.fire('Guardado', 'Respuesta guardada correctamente.', 'success');
      this.verFormulario(this.formularioSeleccionado);
    });
  }

  asignarPregunta(p: any): void {
    if (!this.esAdmin()) return;

    if (!p.asignar_usuario && !p.asignar_rol) {
      Swal.fire('Validación', 'Debe asignar usuario o rol', 'warning');
      return;
    }

    const data = {
      formulario_id: this.formularioSeleccionado.id,
      pregunta_id: p.id,
      usuario_id: p.asignar_usuario || null,
      rol: p.asignar_rol || null
    };

    this.formulariosService.asignar(data).subscribe({
      next: () => {
        Swal.fire('OK', 'Asignado correctamente', 'success');

        p.asignar_usuario = '';
        p.asignar_rol = '';

        this.verFormulario(this.formularioSeleccionado);
      },
      error: (err) => {
        Swal.fire('Error', err.error?.mensaje || 'Error', 'error');
      }
    });
  }

  descargarPDF(): void {
    const id = this.formularioSeleccionado.id;
    window.open(`http://localhost:5000/api/formularios/${id}/pdf`, '_blank');
  }
}