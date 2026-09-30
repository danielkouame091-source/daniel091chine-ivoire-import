import 'package:dio/dio.dart';

import 'models/invoice.dart';

class InvoicesRepository {
  InvoicesRepository(this._dio);
  final Dio _dio;

  Future<List<Invoice>> list({
    String? statut,
    int limit = 50,
    int offset = 0,
  }) async {
    final response = await _dio.get('/api/v1/public/invoices', queryParameters: {
      'limit': limit,
      'page': (offset ~/ limit) + 1,
    });
    final List data = response.data['data'] as List;
    return data.map((e) => Invoice.fromJson(e as Map<String, dynamic>)).toList();
  }

  Future<Invoice> detail(String id) async {
    final response = await _dio.get('/api/v1/portal/client/invoices/$id');
    return Invoice.fromJson(response.data);
  }

  Future<void> recordPayment({
    required String invoiceId,
    required int montant,
    required String mode,
    String? reference,
  }) async {
    await _dio.post('/api/v1/public/payments', data: {
      'invoice_id': invoiceId,
      'date_encaissement': DateTime.now().toIso8601String().substring(0, 10),
      'montant': montant,
      'mode_encaissement': mode,
      'reference_encaissement': reference,
    });
  }

  Future<String> downloadUrl(String id) async {
    final response = await _dio.get('/api/v1/ged/documents/$id/download');
    return response.data['url'] as String;
  }
}
