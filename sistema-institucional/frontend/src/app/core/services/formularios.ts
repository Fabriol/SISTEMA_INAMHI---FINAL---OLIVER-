import { Injectable } from '@angular/core';
import { HttpClient } from '@angular/common/http';
import { Observable } from 'rxjs';

@Injectable({
  providedIn: 'root'
})
export class FormulariosService {

  private api = 'http://localhost:5000/api';

  constructor(private http: HttpClient) { }

  // 🔹 LISTAR FORMULARIOS
  listar(): Observable<any[]> {
    return this.http.get<any[]>(`${this.api}/formularios`);
  }

  // 🔹 CREAR FORMULARIO
  crear(data: any): Observable<any> {
    return this.http.post(`${this.api}/formularios`, data);
  }

  // 🔹 VER FORMULARIO + PREGUNTAS
  ver(id: number): Observable<any> {
    return this.http.get(`${this.api}/formularios/${id}`);
  }

  // 🔹 AGREGAR PREGUNTA
  agregarPregunta(formularioId: number, data: any): Observable<any> {
    return this.http.post(`${this.api}/formularios/${formularioId}/preguntas`, data);
  }

  // 🔹 RESPONDER
  responder(data: any): Observable<any> {
    return this.http.post(`${this.api}/respuestas`, data);
  }

  // * ASIGNAR
  asignar(data: any) {
    return this.http.post('http://localhost:5000/api/formularios/asignar', data);
  }

}