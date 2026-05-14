import { Component, OnInit } from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { RouterModule } from '@angular/router';
import { HttpClient } from '@angular/common/http';
import { DomSanitizer, SafeResourceUrl } from '@angular/platform-browser';
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

  constructor(
    private http: HttpClient,
    private sanitizer: DomSanitizer
  ) {}

  ngOnInit(): void {
    this.usuario = JSON.parse(localStorage.getItem('usuario') || '{}');
    console.log('USUARIO LOGUEADO:', this.usuario);
    this.cargarDocumentos();
  }

  cargarDocumentos(): void {
    this.http.get<any[]>('http://localhost:5000/api/documentos').subscribe({
      next: data => this.documentos = data,
      error: () => Swal.fire('Error', 'No se pudieron cargar documentos', 'error')
    });
  }

  documentosFiltrados(): any[] {
    const texto = this.busqueda.toLowerCase();

    return this.documentos.filter(d =>
      d.titulo?.toLowerCase().includes(texto) ||
      d.descripcion?.toLowerCase().includes(texto) ||
      d.estado?.toLowerCase().includes(texto) ||
      d.creado_por_nombre?.toLowerCase().includes(texto)
    );
  }

  seleccionarArchivo(event: any): void {
    const file = event.target.files[0];

    if (!file) {
      this.archivoSeleccionado = null;
      return;
    }

    if (file.type !== 'application/pdf') {
      Swal.fire('Archivo inválido', 'Solo se permiten archivos PDF', 'warning');
      event.target.value = '';
      this.archivoSeleccionado = null;
      return;
    }

    this.archivoSeleccionado = file;
  }

  guardar(): void {
    if (!this.nuevo.titulo || !this.nuevo.descripcion) {
      Swal.fire('Campos incompletos', 'Ingrese título y descripción', 'warning');
      return;
    }

    const formData = new FormData();
    formData.append('titulo', this.nuevo.titulo);
    formData.append('descripcion', this.nuevo.descripcion);
    formData.append('estado', this.nuevo.estado);
    formData.append('creado_por', this.usuario?.id);

    if (this.archivoSeleccionado) {
      formData.append('archivo', this.archivoSeleccionado);
    }

    this.cargando = true;

    this.http.post('http://localhost:5000/api/documentos', formData).subscribe({
      next: () => {
        this.cargando = false;
        Swal.fire('Creado', 'Documento creado correctamente', 'success');

        this.nuevo = {
          titulo: '',
          descripcion: '',
          estado: 'BORRADOR'
        };

        this.archivoSeleccionado = null;
        this.cerrarPreview();
        this.cargarDocumentos();
      },
      error: (err) => {
        this.cargando = false;
        console.error('ERROR CREAR DOCUMENTO:', err);

        Swal.fire(
          'Error',
          err.error?.mensaje || err.error?.error || 'Error al crear documento',
          'error'
        );
      }
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
    const url = `http://localhost:5000/api/documentos/ver/${limpio}`;

    this.archivoPreviewUrl = url;
    this.archivoPreview = this.sanitizer.bypassSecurityTrustResourceUrl(url);
  }

  descargarArchivo(nombre: string): void {
    const limpio = encodeURIComponent(this.limpiarNombre(nombre));
    window.open(`http://localhost:5000/api/documentos/descargar/${limpio}`, '_blank');
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
    this.http.put(`http://localhost:5000/api/documentos/${this.editando.id}`, this.editando).subscribe({
      next: () => {
        Swal.fire('Actualizado', 'Documento actualizado', 'success');
        this.cerrarModal();
        this.cargarDocumentos();
      },
      error: (err) => {
        Swal.fire('Error', err.error?.mensaje || 'Error al actualizar', 'error');
      }
    });
  }

  eliminar(id: number): void {
    Swal.fire({
      title: '¿Eliminar documento?',
      icon: 'warning',
      showCancelButton: true,
      confirmButtonText: 'Sí, eliminar',
      cancelButtonText: 'Cancelar'
    }).then(result => {
      if (result.isConfirmed) {
        this.http.delete(`http://localhost:5000/api/documentos/${id}`).subscribe({
          next: () => {
            Swal.fire('Eliminado', 'Documento eliminado', 'success');
            this.cerrarPreview();
            this.cargarDocumentos();
          },
          error: (err) => {
            Swal.fire('Error', err.error?.mensaje || 'Error al eliminar', 'error');
          }
        });
      }
    });
  }

  puedeEditarEliminar(d: any): boolean {

  // Admin puede todo
  if (this.usuario?.rol === 'Administrador') return true;

  // Usuario solo sus documentos
  return d.creado_por == this.usuario?.id;
}
}