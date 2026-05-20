import { Injectable } from '@angular/core';
import { HttpClient, HttpHeaders } from '@angular/common/http';
import { Observable } from 'rxjs';

@Injectable({
  providedIn: 'root'
})
export class FormulariosService {

  private api = 'http://localhost:5000/api';

  constructor(private http: HttpClient) { }

  // 🔐 HEADERS CON TOKEN
  private getHeaders() {
    const token = localStorage.getItem('token') || '';

    return {
      headers: new HttpHeaders({
        Authorization: `Bearer ${token}`
      })
    };
  }

  // ===============================
  // 🔹 FORMULARIOS
  // ===============================

  listar(): Observable<any[]> {
    return this.http.get<any[]>(`${this.api}/formularios`, this.getHeaders());
  }

  crear(data: any): Observable<any> {
    return this.http.post(`${this.api}/formularios`, data, this.getHeaders());
  }

  ver(id: number): Observable<any> {
    return this.http.get(`${this.api}/formularios/${id}`, this.getHeaders());
  }

  descargarPDF(id: number): void {
    window.open(`${this.api}/formularios/${id}/pdf`, '_blank');
  }

  // ===============================
  // 🔹 PREGUNTAS
  // ===============================

  agregarPregunta(formularioId: number, data: any): Observable<any> {
    return this.http.post(
      `${this.api}/formularios/${formularioId}/preguntas`,
      data,
      this.getHeaders()
    );
  }

  // ===============================
  // 🔹 ASIGNACIONES (ADMIN)
  // ===============================

  asignar(data: any): Observable<any> {
    return this.http.post(
      `${this.api}/formularios/asignar`,
      data,
      this.getHeaders()
    );
  }

  usuariosDisponibles(): Observable<any[]> {
    return this.http.get<any[]>(
      `${this.api}/formularios/usuarios-disponibles`,
      this.getHeaders()
    );
  }

  // ===============================
  // 🔹 RESPUESTAS
  // ===============================

  responder(data: any): Observable<any> {
    return this.http.post(
      `${this.api}/formularios/responder`,
      data,
      this.getHeaders()
    );
  }

  // ===============================
  // 🔹 USUARIO (PENDIENTES)
  // ===============================

  misPendientes(): Observable<any[]> {
    return this.http.get<any[]>(
      `${this.api}/formularios/mis-pendientes`,
      this.getHeaders()
    );
  }

  

  // ===============================
  // 🔹 NOTIFICACIONES
  // ===============================

  notificaciones(): Observable<any[]> {
    return this.http.get<any[]>(
      `${this.api}/notificaciones`,
      this.getHeaders()
    );
  }

  marcarNotificacionLeida(id: number): Observable<any> {
    return this.http.put(
      `${this.api}/notificaciones/${id}/leer`,
      {},
      this.getHeaders()
    );
  }

  eliminar(id: number): Observable<any> {
    return this.http.delete(`${this.api}/formularios/${id}`);
  }
}