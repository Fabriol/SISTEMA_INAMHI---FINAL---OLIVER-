import { Component, OnInit, ChangeDetectorRef } from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { HttpClient, HttpHeaders } from '@angular/common/http';
import { RouterModule } from '@angular/router';
import { catchError, finalize, forkJoin, of, timeout } from 'rxjs';
import Swal from 'sweetalert2';

@Component({
  selector: 'app-reportes',
  standalone: true,
  imports: [CommonModule, FormsModule, RouterModule],
  templateUrl: './reportes.html',
  styleUrl: './reportes.scss'
})
export class Reportes implements OnInit {

  usuario: any = {};

  // ── Resumen general ──────────────────────────────────────────
  resumen: any = { usuarios: 0, documentos: 0, formularios: 0 };
  cargandoResumen = false;
  errorResumen = '';

  // ── Formularios pendientes ───────────────────────────────────
  formulariosPendientes: any[] = [];
  cargandoPendientes = false;
  errorPendientes = '';

  // ── Búsqueda ─────────────────────────────────────────────────
  busquedaFormulario  = '';
  usuarioSeleccionado = '';   // ID string del usuario filtrado
  dropdownAbierto     = false;

  // ── Estado de envío ──────────────────────────────────────────
  enviandoRecordatorio: Record<string, boolean> = {};
  mensajeAdicional: Record<string, string> = {};

  private readonly api = 'http://localhost:5000/api';

  constructor(
    private http: HttpClient,
    private cdr: ChangeDetectorRef
  ) {}

  ngOnInit(): void {
    this.usuario = JSON.parse(localStorage.getItem('usuario') || '{}');
    this.cargarResumen();
    if (this.puedeVerPendientes()) {
      this.cargarPendientes();
    }
  }

  private headers(): { headers: HttpHeaders } {
    const token = localStorage.getItem('token') || '';
    return { headers: new HttpHeaders({ Authorization: `Bearer ${token}` }) };
  }

  esAdmin(): boolean {
    return this.usuario?.rol === 'Administrador';
  }

  esTalentoHumano(): boolean {
    const r = (this.usuario?.rol || '').toLowerCase()
      .normalize('NFD').replace(/[̀-ͯ]/g, '').trim();
    return r.includes('talento humano') && r.includes('recep');
  }

  puedeVerPendientes(): boolean {
    return this.esAdmin() || this.esTalentoHumano();
  }

  // ── Resumen ───────────────────────────────────────────────────
  cargarResumen(): void {
    this.cargandoResumen = true;
    forkJoin({
      resumen: this.http.get<any>(`${this.api}/reportes/resumen`, this.headers()),
      formularios: this.http.get<any[]>(`${this.api}/formularios`, this.headers())
    }).pipe(
      timeout(8000),
      catchError((err: any) => {
        this.errorResumen = err?.error?.mensaje || 'Error al cargar resumen';
        return of({ resumen: { usuarios: 0, documentos: 0 }, formularios: [] });
      }),
      finalize(() => { this.cargandoResumen = false; this.cdr.detectChanges(); })
    ).subscribe((res: any) => {
      const r = res.resumen || {};
      const fs: any[] = res.formularios || [];
      this.resumen = {
        usuarios:   r.usuarios   || 0,
        documentos: r.documentos || 0,
        formularios: fs.length,
        formularios_100: fs.filter((f: any) => (f.porcentaje ?? 0) >= 100).length,
        formularios_proceso: fs.filter((f: any) => (f.porcentaje ?? 0) > 0 && (f.porcentaje ?? 0) < 100).length,
      };
      this.cdr.detectChanges();
    });
  }

  // ── Formularios pendientes ────────────────────────────────────
  cargarPendientes(): void {
    this.cargandoPendientes = true;
    this.errorPendientes = '';
    this.http.get<any[]>(`${this.api}/reportes/formularios-pendientes`, this.headers()).pipe(
      timeout(10000),
      catchError((err: any) => {
        if (err.status === 403) {
          this.errorPendientes = 'No tiene permisos para ver esta sección.';
        } else {
          this.errorPendientes = err?.error?.mensaje || 'Error al cargar formularios pendientes.';
        }
        return of([]);
      }),
      finalize(() => { this.cargandoPendientes = false; this.cdr.detectChanges(); })
    ).subscribe((data: any[]) => {
      this.formulariosPendientes = (data ?? []).filter(f => (f.pendientes ?? 0) > 0);
      this.cdr.detectChanges();
    });
  }

  // ── Lista de usuarios únicos con pendientes (para el dropdown) ──
  get usuariosUnicos(): any[] {
    const mapa = new Map<string, any>();
    this.formulariosPendientes.forEach(f => {
      (f.usuarios_pendientes || []).forEach((u: any) => {
        const key = String(u.usuario_id);
        if (!mapa.has(key)) {
          mapa.set(key, {
            usuario_id:     u.usuario_id,
            nombre_completo: u.nombre_completo || `${u.nombres} ${u.apellidos}`.trim(),
            usuario:        u.usuario,
          });
        }
      });
    });
    return Array.from(mapa.values()).sort((a, b) =>
      a.nombre_completo.localeCompare(b.nombre_completo)
    );
  }

  get labelUsuarioSeleccionado(): string {
    if (!this.usuarioSeleccionado) return 'Todos los usuarios';
    const u = this.usuariosUnicos.find(x => String(x.usuario_id) === this.usuarioSeleccionado);
    return u ? u.nombre_completo : 'Todos los usuarios';
  }

  seleccionarUsuario(id: string): void {
    this.usuarioSeleccionado = id;
    this.dropdownAbierto = false;
  }

  limpiarUsuario(): void {
    this.usuarioSeleccionado = '';
    this.dropdownAbierto = false;
  }

  toggleDropdown(): void {
    this.dropdownAbierto = !this.dropdownAbierto;
  }

  // ── Filtros ───────────────────────────────────────────────────
  get formulariosFiltrados(): any[] {
    const textoF = this.busquedaFormulario.toLowerCase().trim();

    return this.formulariosPendientes.filter(f => {
      const matchF = !textoF || (f.titulo || '').toLowerCase().includes(textoF);
      const matchU = !this.usuarioSeleccionado ||
        (f.usuarios_pendientes || []).some((u: any) =>
          String(u.usuario_id) === this.usuarioSeleccionado
        );
      return matchF && matchU;
    });
  }

  usuariosFiltrados(f: any): any[] {
    if (!this.usuarioSeleccionado) return f.usuarios_pendientes || [];
    return (f.usuarios_pendientes || []).filter((u: any) =>
      String(u.usuario_id) === this.usuarioSeleccionado
    );
  }

  // ── Enviar recordatorio ───────────────────────────────────────
  enviarRecordatorio(formulario: any, usuario: any): void {
    const key = `${formulario.id}_${usuario.usuario_id}`;
    if (this.enviandoRecordatorio[key]) return;

    const nombreUser = (usuario.nombre_completo ||
      `${usuario.nombres || ''} ${usuario.apellidos || ''}`.trim()) || usuario.usuario;

    Swal.fire({
      title: '¿Enviar recordatorio?',
      html: `
        <div style="text-align:left;font-size:14px;line-height:1.6">
          <p>Se enviará una notificación a <strong>${nombreUser}</strong>.</p>
          <p>Formulario: <strong>"${formulario.titulo}"</strong></p>
          <p>Campos pendientes: <strong style="color:#dc2626">${usuario.pendientes}</strong></p>
        </div>
        <textarea
          id="swal-msg-extra"
          class="swal2-textarea"
          placeholder="Mensaje adicional para el usuario (opcional)..."
          rows="3"
          style="resize:vertical;font-size:13px;margin-top:12px;width:100%;box-sizing:border-box;"
        >${this.mensajeAdicional[key] || ''}</textarea>
      `,
      icon: 'question',
      showCancelButton: true,
      confirmButtonText: '📧 Enviar recordatorio',
      cancelButtonText: 'Cancelar',
      confirmButtonColor: '#1e3a8a',
      focusConfirm: false,
      preConfirm: () => {
        const el = document.getElementById('swal-msg-extra') as HTMLTextAreaElement | null;
        return el ? el.value.trim() : '';
      },
    }).then(result => {
      if (!result.isConfirmed) return;

      const extra: string = (result.value as string) || '';
      this.mensajeAdicional[key] = extra;
      this.enviandoRecordatorio[key] = true;
      this.cdr.detectChanges();

      this.http.post<any>(`${this.api}/reportes/enviar-recordatorio`, {
        usuario_id:    usuario.usuario_id,
        formulario_id: formulario.id,
        mensaje:       extra,
      }, this.headers()).pipe(
        timeout(10000),
        catchError((err: any) => {
          const msg = err?.error?.mensaje ?? 'No se pudo enviar el recordatorio.';
          // 409 = recordatorio sin leer ya existe (deduplicación)
          const icon = err?.status === 409 ? 'warning' : 'error';
          Swal.fire({ icon, title: icon === 'warning' ? 'Aviso' : 'Error', text: msg });
          return of(null);
        }),
        finalize(() => { this.enviandoRecordatorio[key] = false; this.cdr.detectChanges(); })
      ).subscribe((res: any) => {
        if (!res) return;
        this.mensajeAdicional[key] = '';

        const camposTexto = res.campos?.length
          ? `<br><small style="color:#475569">Campos: ${(res.campos as string[]).slice(0, 8).join(', ')}${res.campos.length > 8 ? '…' : ''}</small>`
          : '';

        Swal.fire({
          icon: 'success',
          title: 'Recordatorio enviado',
          html: `${res.mensaje ?? 'Recordatorio enviado correctamente.'}${camposTexto}`,
          confirmButtonColor: '#1e3a8a',
        });

        // Recargar la lista para reflejar el estado actualizado
        this.cargarPendientes();
      });
    });
  }

  colorPorcentaje(p: number): string {
    if (p >= 100) return '#16a34a';
    if (p >= 50)  return '#d97706';
    return '#dc2626';
  }
}
