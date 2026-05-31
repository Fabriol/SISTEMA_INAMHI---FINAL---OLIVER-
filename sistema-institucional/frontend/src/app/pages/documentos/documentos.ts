import { Component, OnInit, ChangeDetectorRef } from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { RouterModule } from '@angular/router';
import { HttpClient, HttpHeaders } from '@angular/common/http';
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

  errorArchivo = '';
  errorArchivoEdicion = '';

  usuario: any = {};
  archivoSeleccionado: File | null = null;
  archivoEdicionSeleccionado: File | null = null;

  nuevo: any = {
    titulo: '',
    descripcion: ''
  };

  mostrarModal = false;
  editando: any = null;

  archivoPreview: SafeResourceUrl | null = null;
  archivoPreviewUrl = '';

  formulariosPazSalvo: any[] = [];
  cargandoFormularios = false;

  private api = 'http://localhost:5000/api';
  private alertaActiva = false;

  constructor(
    private http: HttpClient,
    private sanitizer: DomSanitizer,
    private cdr: ChangeDetectorRef
  ) { }

  ngOnInit(): void {
    this.usuario = JSON.parse(localStorage.getItem('usuario') || '{}');
    this.cargarDocumentos();
    if (this.esTalentoHumanoCR() || this.esExFuncionario()) {
      this.cargarFormulariosPazSalvo();
    }
  }

  private getHeaders(): { headers: HttpHeaders } {
    const token = localStorage.getItem('token') || '';
    return { headers: new HttpHeaders({ Authorization: `Bearer ${token}` }) };
  }

  esTalentoHumanoCR(): boolean {
    const r = this.normalizarRol();
    return r.includes('talento humano') && r.includes('recep');
  }

  esExFuncionario(): boolean {
    const r = this.normalizarRol();
    return r.includes('ex funcionario') || r.includes('ex-funcionario') || r.includes('exfuncionario');
  }

  cargarFormulariosPazSalvo(): void {
    this.cargandoFormularios = true;
    this.http.get<any[]>(`${this.api}/formularios`, this.getHeaders()).pipe(
      timeout(8000),
      catchError(() => of([])),
      finalize(() => { this.cargandoFormularios = false; this.cdr.detectChanges(); })
    ).subscribe((data: any[]) => {
      this.formulariosPazSalvo = (data ?? []).map(f => ({
        ...f,
        porcentaje: f.porcentaje ?? 0
      }));
      this.cdr.detectChanges();
    });
  }

  get formulariosCompletados(): any[] {
    return this.formulariosPazSalvo.filter(f => (f.porcentaje ?? 0) >= 100);
  }

  get formulariosEnProceso(): any[] {
    return this.formulariosPazSalvo.filter(f => (f.porcentaje ?? 0) < 100);
  }

  verFormularioPDF(f: any): void {
    window.open(`${this.api}/formularios/${f.id}/pdf`, '_blank');
  }

  aprobarFormulario(f: any): void {
    Swal.fire({
      title: '¿Aprobar formulario?',
      text: `Se marcará como aprobado el formulario "${f.titulo}"`,
      icon: 'question',
      showCancelButton: true,
      confirmButtonText: 'Sí, aprobar',
      cancelButtonText: 'Cancelar',
    }).then(result => {
      if (!result.isConfirmed) return;
      this.http.patch(`${this.api}/formularios/${f.id}/aprobar`, {}, this.getHeaders()).pipe(
        timeout(8000),
        catchError((err: any) => {
          Swal.fire('Error', err?.error?.mensaje ?? 'Error al aprobar.', 'error');
          return of(null);
        })
      ).subscribe((res: any) => {
        if (!res) return;
        Swal.fire('Aprobado', res.mensaje ?? 'Formulario aprobado.', 'success');
        f.estado = 'APROBADO';
        this.cdr.detectChanges();
      });
    });
  }

  normalizarRol(): string {
    return String(this.usuario?.rol || '')
      .toLowerCase()
      .normalize('NFD')
      .replace(/[\u0300-\u036f]/g, '')
      .trim();
  }

  esAdministrador(): boolean {
    const rol = this.normalizarRol();
    return rol === 'administrador' || rol === 'admin';
  }

  esRecursosHumanos(): boolean {
    const rol = this.normalizarRol();
    return (
      rol === 'recursos humanos' ||
      rol === 'rrhh' ||
      rol === 'talento humano' ||
      rol === 'recursos_humanos'
    );
  }

  puedeSubirDocumento(): boolean {
    return !this.esRecursosHumanos();
  }

  puedeVerListadoDocumentos(): boolean {
    return this.esAdministrador() || this.esRecursosHumanos();
  }

  puedeVerMisDocumentos(): boolean {
    return !this.esAdministrador() && !this.esRecursosHumanos();
  }

  puedePrevisualizarDocumentos(): boolean {
    return this.esAdministrador() || this.esRecursosHumanos();
  }

  puedeEditarDocumento(d: any): boolean {
    if (!d) return false;
    if (this.esAdministrador() || this.esRecursosHumanos()) return false;

    return String(d.creado_por) === String(this.usuario?.id);
  }

  puedeEliminarDocumento(): boolean {
    return this.esAdministrador();
  }

  alertaRapida(titulo: string, texto: string): void {
    if (this.alertaActiva) return;

    this.alertaActiva = true;

    Swal.fire({
      icon: 'error',
      title: titulo,
      text: texto,
      timer: 1400,
      showConfirmButton: false
    }).then(() => {
      this.alertaActiva = false;
    });
  }

  limpiarTexto(texto: string): string {
    return String(texto || '').trim().replace(/\s+/g, ' ');
  }

  campoTextoValido(texto: string): boolean {
    return /^[a-zA-ZÁÉÍÓÚáéíóúÑñ0-9\s.,;:()\-_/]+$/.test(texto || '');
  }

  validarTextoTiempoReal(event: Event, objeto: any, campo: string): void {
    const input = event.target as HTMLInputElement;
    let valor = input.value || '';
    const valorOriginal = valor;

    valor = valor.replace(/[^a-zA-ZÁÉÍÓÚáéíóúÑñ0-9\s.,;:()\-_/]/g, '');
    valor = valor.replace(/\s{2,}/g, ' ');

    const limite = campo === 'titulo' ? 80 : 150;

    if (valor.length > limite) {
      valor = valor.substring(0, limite);
      this.alertaRapida('Límite alcanzado', `Máximo ${limite} caracteres.`);
    }

    if (valorOriginal !== valor) {
      this.alertaRapida(
        'Caracter inválido',
        'Solo se permiten letras, números y signos básicos.'
      );
    }

    input.value = valor;
    objeto[campo] = valor;
  }

  validarPdf(file: File | undefined | null): string {
    if (!file) {
      return 'Debe seleccionar un archivo PDF.';
    }

    const nombre = file.name.toLowerCase();
    const esPdf = file.type === 'application/pdf' || nombre.endsWith('.pdf');

    if (!esPdf) {
      return 'Solo se permiten archivos en formato PDF.';
    }

    if (file.size <= 0) {
      return 'El archivo seleccionado está vacío.';
    }

    return '';
  }

  seleccionarArchivo(event: Event): void {
    const input = event.target as HTMLInputElement;
    const file = input.files?.[0];

    this.errorArchivo = '';
    this.archivoSeleccionado = null;

    const error = this.validarPdf(file);

    if (error) {
      this.errorArchivo = error;
      Swal.fire('Archivo inválido', error, 'warning');
      input.value = '';
      return;
    }

    this.archivoSeleccionado = file!;
  }

  seleccionarArchivoEdicion(event: Event): void {
    const input = event.target as HTMLInputElement;
    const file = input.files?.[0];

    this.errorArchivoEdicion = '';
    this.archivoEdicionSeleccionado = null;

    if (!file) return;

    const error = this.validarPdf(file);

    if (error) {
      this.errorArchivoEdicion = error;
      Swal.fire('Archivo inválido', error, 'warning');
      input.value = '';
      return;
    }

    this.archivoEdicionSeleccionado = file;
  }

  cargarDocumentos(): void {
    this.cargando = true;
    this.error = '';

    this.http.get<any[]>(`${this.api}/documentos`).pipe(
      timeout(7000),
      catchError((err: any) => {
        this.error = err.error?.mensaje || err.error?.error || 'No se pudieron cargar documentos';
        Swal.fire('Error', this.error, 'error');
        return of([]);
      }),
      finalize(() => {
        this.cargando = false;
        this.cdr.detectChanges();
      })
    ).subscribe((data: any[]) => {
      this.documentos = Array.isArray(data) ? data : [];
      this.cdr.detectChanges();
    });
  }

  documentosFiltrados(): any[] {
    let lista = [...this.documentos];

    if (!this.esAdministrador() && this.esRecursosHumanos()) {
      return lista;
    }

    if (!this.esAdministrador()) {
      return this.misDocumentos();
    }

    const texto = this.busqueda.toLowerCase().trim();

    if (!texto) return lista;

    return lista.filter(d => {
      const titulo = String(d.titulo || '').toLowerCase();
      const descripcion = String(d.descripcion || '').toLowerCase();
      const usuario = String(
        d.creado_por_nombre ||
        d.usuario_nombre ||
        d.nombres ||
        d.usuario ||
        ''
      ).toLowerCase();

      return (
        titulo.includes(texto) ||
        descripcion.includes(texto) ||
        usuario.includes(texto)
      );
    });
  }

  misDocumentos(): any[] {
    return this.documentos.filter(d =>
      String(d.creado_por) === String(this.usuario?.id)
    );
  }

  validarFormularioNuevo(): boolean {
    this.nuevo.titulo = this.limpiarTexto(this.nuevo.titulo);
    this.nuevo.descripcion = this.limpiarTexto(this.nuevo.descripcion);

    if (!this.puedeSubirDocumento()) {
      Swal.fire('Sin permisos', 'Su rol no puede subir documentos.', 'warning');
      return false;
    }

    if (!this.usuario?.id) {
      Swal.fire('Sesión inválida', 'No se encontró el usuario autenticado.', 'error');
      return false;
    }

    if (!this.nuevo.titulo || !this.nuevo.descripcion) {
      Swal.fire('Campos incompletos', 'Ingrese título y descripción.', 'warning');
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

    if (this.nuevo.titulo.length > 80) {
      Swal.fire('Validación', 'El título no debe superar 80 caracteres.', 'warning');
      return false;
    }

    if (this.nuevo.descripcion.length > 150) {
      Swal.fire('Validación', 'La descripción no debe superar 150 caracteres.', 'warning');
      return false;
    }

    const errorPdf = this.validarPdf(this.archivoSeleccionado);

    if (errorPdf) {
      this.errorArchivo = errorPdf;
      Swal.fire('Archivo requerido', errorPdf, 'warning');
      return false;
    }

    return true;
  }

  validarFormularioEdicion(): boolean {
    if (!this.editando) {
      Swal.fire('Error', 'No hay documento seleccionado para editar.', 'error');
      return false;
    }

    if (!this.puedeEditarDocumento(this.editando)) {
      Swal.fire('Sin permisos', 'Solo puede editar documentos subidos por usted.', 'warning');
      return false;
    }

    this.editando.titulo = this.limpiarTexto(this.editando.titulo);
    this.editando.descripcion = this.limpiarTexto(this.editando.descripcion);

    if (!this.editando.titulo || !this.editando.descripcion) {
      Swal.fire('Campos incompletos', 'Complete título y descripción.', 'warning');
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

    if (this.editando.titulo.length > 80) {
      Swal.fire('Validación', 'El título no debe superar 80 caracteres.', 'warning');
      return false;
    }

    if (this.editando.descripcion.length > 150) {
      Swal.fire('Validación', 'La descripción no debe superar 150 caracteres.', 'warning');
      return false;
    }

    if (this.errorArchivoEdicion) {
      Swal.fire('Archivo inválido', this.errorArchivoEdicion, 'warning');
      return false;
    }

    return true;
  }

  guardar(): void {
    if (this.cargando) return;
    if (!this.validarFormularioNuevo()) return;

    const formData = new FormData();
    formData.append('titulo', this.nuevo.titulo);
    formData.append('descripcion', this.nuevo.descripcion);
    formData.append('creado_por', String(this.usuario.id));
    formData.append('archivo', this.archivoSeleccionado as File);

    this.cargando = true;

    this.http.post(`${this.api}/documentos`, formData).pipe(
      timeout(10000),
      catchError((err: any) => {
        Swal.fire(
          'Error',
          err.error?.mensaje || err.error?.error || 'Error al subir documento',
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

      Swal.fire('Subido', 'Documento subido correctamente.', 'success');

      this.nuevo = {
        titulo: '',
        descripcion: ''
      };

      this.archivoSeleccionado = null;
      this.errorArchivo = '';
      this.cargarDocumentos();
    });
  }

  abrirEditar(d: any): void {
    if (!this.puedeEditarDocumento(d)) {
      Swal.fire('Sin permisos', 'Solo puede editar documentos subidos por usted.', 'warning');
      return;
    }

    this.editando = { ...d };
    this.archivoEdicionSeleccionado = null;
    this.errorArchivoEdicion = '';
    this.mostrarModal = true;
  }

  cerrarModal(): void {
    this.mostrarModal = false;
    this.editando = null;
    this.archivoEdicionSeleccionado = null;
    this.errorArchivoEdicion = '';
  }

  guardarEdicion(): void {
    if (this.cargando) return;
    if (!this.validarFormularioEdicion()) return;

    const formData = new FormData();
    formData.append('titulo', this.editando.titulo);
    formData.append('descripcion', this.editando.descripcion);
    formData.append('creado_por', String(this.usuario.id));

    if (this.archivoEdicionSeleccionado) {
      formData.append('archivo', this.archivoEdicionSeleccionado);
    }

    this.cargando = true;

    this.http.put(`${this.api}/documentos/${this.editando.id}`, formData).pipe(
      timeout(10000),
      catchError((err: any) => {
        Swal.fire(
          'Error',
          err.error?.mensaje || err.error?.error || 'Error al actualizar documento',
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

      Swal.fire('Actualizado', 'Documento actualizado correctamente.', 'success');
      this.cerrarModal();
      this.cargarDocumentos();
    });
  }

  eliminar(id: number): void {
    if (!this.esAdministrador()) {
      Swal.fire('Sin permisos', 'Solo el administrador puede eliminar documentos.', 'warning');
      return;
    }

    if (!id) {
      Swal.fire('Error', 'ID de documento inválido.', 'error');
      return;
    }

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
        timeout(7000),
        catchError((err: any) => {
          Swal.fire(
            'Error',
            err.error?.mensaje || err.error?.error || 'Error al eliminar documento',
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

        Swal.fire('Eliminado', 'Documento eliminado correctamente.', 'success');
        this.cerrarPreview();
        this.cargarDocumentos();
      });
    });
  }

  limpiarNombre(nombre: string): string {
    return String(nombre || '')
      .replace('uploads/', '')
      .replace('uploads\\', '')
      .split('/').pop()!
      .split('\\').pop()!;
  }

  verArchivo(nombre: string): void {

    if (!this.puedePrevisualizarDocumentos()) {
      Swal.fire(
        'Sin permisos',
        'Solo administrador y Recursos Humanos pueden visualizar documentos.',
        'warning'
      );
      return;
    }

    const limpio = encodeURIComponent(this.limpiarNombre(nombre));

    const token =
      localStorage.getItem('token') ||
      localStorage.getItem('auth_token') ||
      '';

    const url = token
      ? `${this.api}/documentos/ver/${limpio}?token=${token}`
      : `${this.api}/documentos/ver/${limpio}`;

    this.archivoPreviewUrl = url;

    this.archivoPreview =
      this.sanitizer.bypassSecurityTrustResourceUrl(url);
  }

  descargarArchivo(nombre: string): void {
    if (!nombre) {
      Swal.fire('Archivo no disponible', 'Este documento no tiene archivo asociado.', 'warning');
      return;
    }

    const limpio = encodeURIComponent(this.limpiarNombre(nombre));

    const token =
      localStorage.getItem('token') ||
      localStorage.getItem('auth_token') ||
      '';

    const url = token
      ? `${this.api}/documentos/descargar/${limpio}?token=${token}`
      : `${this.api}/documentos/descargar/${limpio}`;

    window.open(url, '_blank');
  }

  cerrarPreview(): void {
    this.archivoPreview = null;
    this.archivoPreviewUrl = '';
  }

  esPDF(): boolean {
    return this.archivoPreviewUrl.toLowerCase().includes('.pdf');
  }
}