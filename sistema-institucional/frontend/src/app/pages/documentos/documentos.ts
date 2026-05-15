import { Component, OnInit, ChangeDetectorRef } from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { RouterModule } from '@angular/router';
import { HttpClient } from '@angular/common/http';
import { DomSanitizer, SafeResourceUrl } from '@angular/platform-browser';
import { catchError, finalize, of, timeout } from 'rxjs';
import Swal from 'sweetalert2';

@Component({
  selector: 'app-documentos',
  standalone: true,
  imports: [CommonModule, FormsModule, RouterModule],
  templateUrl: './documentos.html',
  styleUrl: './documentos.scss'
})
export class Documentos implements OnInit {

  documentos: any[] = [];
  busqueda = '';
  cargando = false;
  error = '';

  usuario: any = {};
  archivoSeleccionado: File | null = null;

  nuevo: any = {
    titulo: '',
    descripcion: '',
    estado: 'BORRADOR'
  };

  mostrarModal = false;
  editando: any = null;

  archivoPreview: SafeResourceUrl | null = null;
  archivoPreviewUrl = '';

  private api = 'http://localhost:5000/api';
  private alertaActiva = false;

  constructor(
    private http: HttpClient,
    private sanitizer: DomSanitizer,
    private cdr: ChangeDetectorRef
  ) {}

  ngOnInit(): void {
    this.usuario = JSON.parse(localStorage.getItem('usuario') || '{}');
    this.cargarDocumentos();
  }

  alertaRapida(titulo: string, texto: string): void {
    if (this.alertaActiva) return;

    this.alertaActiva = true;

    Swal.fire({
      icon: 'error',
      title: titulo,
      text: texto,
      timer: 1300,
      showConfirmButton: false
    }).then(() => {
      this.alertaActiva = false;
    });
  }

  limpiarTexto(texto: string): string {
    return (texto || '').trim().replace(/\s+/g, ' ');
  }

  campoTextoValido(texto: string): boolean {
    return /^[a-zA-ZÁÉÍÓÚáéíóúÑñ0-9\s.,;:()\-_/]+$/.test(texto || '');
  }

  estadoValido(estado: string): boolean {
    return ['BORRADOR', 'PENDIENTE', 'APROBADO', 'RECHAZADO', 'FINALIZADO'].includes(estado);
  }

  validarTextoTiempoReal(event: any, objeto: any, campo: string): void {
    const valor = event.target.value;

    if (/[^a-zA-ZÁÉÍÓÚáéíóúÑñ0-9\s.,;:()\-_/]/.test(valor)) {
      this.alertaRapida(
        'Caracter inválido',
        'Este campo solo permite letras, números y signos básicos.'
      );
    }

    objeto[campo] = valor;
  }

  cargarDocumentos(): void {
    this.cargando = true;
    this.error = '';

    this.http.get<any[]>(`${this.api}/documentos`).pipe(
      timeout(4000),
      catchError((err: any) => {
        this.error = err.error?.mensaje || 'No se pudieron cargar documentos';
        Swal.fire('Error', this.error, 'error');
        return of([]);
      }),
      finalize(() => {
        this.cargando = false;
        this.cdr.detectChanges();
      })
    ).subscribe((data: any[]) => {
      this.documentos = data || [];
      this.cdr.detectChanges();
    });
  }

  documentosFiltrados(): any[] {
    const texto = this.busqueda.toLowerCase().trim();

    if (!texto) return this.documentos;

    return this.documentos.filter(d =>
      d.titulo?.toLowerCase().includes(texto) ||
      d.descripcion?.toLowerCase().includes(texto) ||
      d.estado?.toLowerCase().includes(texto) ||
      d.creado_por_nombre?.toLowerCase().includes(texto)
    );
  }

  validarFormularioNuevo(): boolean {
    this.nuevo.titulo = this.limpiarTexto(this.nuevo.titulo);
    this.nuevo.descripcion = this.limpiarTexto(this.nuevo.descripcion);

    if (!this.nuevo.titulo || !this.nuevo.descripcion || !this.nuevo.estado) {
      Swal.fire('Campos incompletos', 'Ingrese título, descripción y estado.', 'warning');
      return false;
    }

    if (!this.campoTextoValido(this.nuevo.titulo)) {
      Swal.fire('Validación', 'El título contiene caracteres inválidos.', 'error');
      return false;
    }

    if (!this.campoTextoValido(this.nuevo.descripcion)) {
      Swal.fire('Validación', 'La descripción contiene caracteres inválidos.', 'error');
      return false;
    }

    if (this.nuevo.titulo.length < 3) {
      Swal.fire('Validación', 'El título debe tener mínimo 3 caracteres.', 'warning');
      return false;
    }

    if (this.nuevo.descripcion.length < 5) {
      Swal.fire('Validación', 'La descripción debe tener mínimo 5 caracteres.', 'warning');
      return false;
    }

    if (this.nuevo.titulo.length > 120) {
      Swal.fire('Validación', 'El título no debe superar 120 caracteres.', 'warning');
      return false;
    }

    if (this.nuevo.descripcion.length > 500) {
      Swal.fire('Validación', 'La descripción no debe superar 500 caracteres.', 'warning');
      return false;
    }

    return true;
  }

  validarFormularioEdicion(): boolean {
    this.editando.titulo = this.limpiarTexto(this.editando.titulo);
    this.editando.descripcion = this.limpiarTexto(this.editando.descripcion);

    if (!this.editando.titulo || !this.editando.descripcion || !this.editando.estado) {
      Swal.fire('Campos incompletos', 'Complete título, descripción y estado.', 'warning');
      return false;
    }

    if (!this.campoTextoValido(this.editando.titulo)) {
      Swal.fire('Validación', 'El título contiene caracteres inválidos.', 'error');
      return false;
    }

    if (!this.campoTextoValido(this.editando.descripcion)) {
      Swal.fire('Validación', 'La descripción contiene caracteres inválidos.', 'error');
      return false;
    }

    if (this.editando.titulo.length < 3) {
      Swal.fire('Validación', 'El título debe tener mínimo 3 caracteres.', 'warning');
      return false;
    }

    if (this.editando.descripcion.length < 5) {
      Swal.fire('Validación', 'La descripción debe tener mínimo 5 caracteres.', 'warning');
      return false;
    }

    return true;
  }

  seleccionarArchivo(event: any): void {
    const file = event.target.files[0];

    if (!file) {
      this.archivoSeleccionado = null;
      return;
    }

    if (file.type !== 'application/pdf') {
      Swal.fire('Archivo inválido', 'Solo se permiten archivos PDF.', 'warning');
      event.target.value = '';
      this.archivoSeleccionado = null;
      return;
    }

    if (file.size > 10 * 1024 * 1024) {
      Swal.fire('Archivo muy pesado', 'El PDF no debe superar los 10 MB.', 'warning');
      event.target.value = '';
      this.archivoSeleccionado = null;
      return;
    }

    this.archivoSeleccionado = file;
  }

  guardar(): void {
    if (this.cargando) return;
    if (!this.validarFormularioNuevo()) return;

    const formData = new FormData();
    formData.append('titulo', this.nuevo.titulo);
    formData.append('descripcion', this.nuevo.descripcion);
    formData.append('estado', this.nuevo.estado);
    formData.append('creado_por', String(this.usuario?.id || ''));

    if (this.archivoSeleccionado) {
      formData.append('archivo', this.archivoSeleccionado);
    }

    this.cargando = true;

    this.http.post(`${this.api}/documentos`, formData).pipe(
      timeout(5000),
      catchError((err: any) => {
        Swal.fire(
          'Error',
          err.error?.mensaje || err.error?.error || 'Error al crear documento',
          'error'
        );
        return of(null);
      }),
      finalize(() => {
        this.cargando = false;
        this.cdr.detectChanges();
      })
    ).subscribe((res: any) => {
      if (!res) return;

      Swal.fire('Creado', 'Documento creado correctamente.', 'success');

      this.nuevo = {
        titulo: '',
        descripcion: '',
        estado: 'BORRADOR'
      };

      this.archivoSeleccionado = null;
      this.cerrarPreview();
      this.cargarDocumentos();
    });
  }

  limpiarNombre(nombre: string): string {
    return nombre
      .replace('uploads/', '')
      .replace('uploads\\', '')
      .split('/').pop()!
      .split('\\').pop()!;
  }

  verArchivo(nombre: string): void {
    const limpio = encodeURIComponent(this.limpiarNombre(nombre));
    const url = `${this.api}/documentos/ver/${limpio}`;

    this.archivoPreviewUrl = url;
    this.archivoPreview = this.sanitizer.bypassSecurityTrustResourceUrl(url);
  }

  descargarArchivo(nombre: string): void {
    const limpio = encodeURIComponent(this.limpiarNombre(nombre));
    window.open(`${this.api}/documentos/descargar/${limpio}`, '_blank');
  }

  cerrarPreview(): void {
    this.archivoPreview = null;
    this.archivoPreviewUrl = '';
  }

  esPDF(): boolean {
    return this.archivoPreviewUrl.toLowerCase().includes('.pdf');
  }

  abrirEditar(d: any): void {
    this.editando = { ...d };
    this.mostrarModal = true;
  }

  cerrarModal(): void {
    this.mostrarModal = false;
    this.editando = null;
  }

  guardarEdicion(): void {
    if (this.cargando) return;
    if (!this.validarFormularioEdicion()) return;

    this.cargando = true;

    this.http.put(`${this.api}/documentos/${this.editando.id}`, this.editando).pipe(
      timeout(4000),
      catchError((err: any) => {
        Swal.fire('Error', err.error?.mensaje || 'Error al actualizar', 'error');
        return of(null);
      }),
      finalize(() => {
        this.cargando = false;
        this.cdr.detectChanges();
      })
    ).subscribe((res: any) => {
      if (!res) return;

      Swal.fire('Actualizado', 'Documento actualizado correctamente.', 'success');
      this.cerrarModal();
      this.cargarDocumentos();
    });
  }

  eliminar(id: number): void {
    Swal.fire({
      title: '¿Eliminar documento?',
      text: 'Esta acción no se puede deshacer.',
      icon: 'warning',
      showCancelButton: true,
      confirmButtonText: 'Sí, eliminar',
      cancelButtonText: 'Cancelar',
      confirmButtonColor: '#dc2626'
    }).then(result => {
      if (!result.isConfirmed) return;

      this.cargando = true;

      this.http.delete(`${this.api}/documentos/${id}`).pipe(
        timeout(4000),
        catchError((err: any) => {
          Swal.fire('Error', err.error?.mensaje || 'Error al eliminar', 'error');
          return of(null);
        }),
        finalize(() => {
          this.cargando = false;
          this.cdr.detectChanges();
        })
      ).subscribe((res: any) => {
        if (!res) return;

        Swal.fire('Eliminado', 'Documento eliminado correctamente.', 'success');
        this.cerrarPreview();
        this.cargarDocumentos();
      });
    });
  }

  puedeEditarEliminar(d: any): boolean {
    if (this.usuario?.rol === 'Administrador') return true;
    return d.creado_por == this.usuario?.id;
  }
}