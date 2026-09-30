import 'package:dio/dio.dart';

import 'api_client.dart';

class ErrorInterceptor extends Interceptor {
  @override
  void onError(DioException err, ErrorInterceptorHandler handler) {
    final response = err.response;

    if (response == null) {
      return handler.reject(DioException(
        requestOptions: err.requestOptions,
        error: ApiException(
          statusCode: 0,
          code: 'NETWORK_ERROR',
          message: 'Pas de connexion réseau. Vérifiez votre connexion.',
        ),
        type: err.type,
      ));
    }

    final data = response.data;
    String code = 'HTTP_${response.statusCode}';
    String message = 'Erreur ${response.statusCode}';
    Map<String, dynamic>? details;

    if (data is Map<String, dynamic>) {
      code    = (data['code'] as String?) ?? code;
      message = (data['message'] as String?) ?? message;
      details = data['details'] as Map<String, dynamic>?;
    }

    handler.reject(DioException(
      requestOptions: err.requestOptions,
      response: response,
      error: ApiException(
        statusCode: response.statusCode ?? 0,
        code: code,
        message: message,
        details: details,
      ),
      type: err.type,
    ));
  }
}
