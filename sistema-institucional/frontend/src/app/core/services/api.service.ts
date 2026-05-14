import { Injectable } from '@angular/core';
import { HttpClient } from '@angular/common/http';

@Injectable({
  providedIn: 'root'
})
export class ApiService {

  // 👉 URL DE TU BACKEND
  private API = 'http://localhost:5000/api';

  constructor(private http: HttpClient) {}

  // =========================
  // GET
  // =========================
  get(endpoint: string) {
    return this.http.get(`${this.API}/${endpoint}`);
  }

  // =========================
  // POST
  // =========================
  post(endpoint: string, data: any) {
    return this.http.post(`${this.API}/${endpoint}`, data);
  }

  // =========================
  // PUT
  // =========================
  put(endpoint: string, data: any) {
    return this.http.put(`${this.API}/${endpoint}`, data);
  }

  // =========================
  // DELETE
  // =========================
  delete(endpoint: string) {
    return this.http.delete(`${this.API}/${endpoint}`);
  }
}