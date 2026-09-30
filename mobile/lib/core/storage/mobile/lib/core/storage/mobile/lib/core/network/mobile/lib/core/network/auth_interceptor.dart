import 'package:dio/dio.dart';

import '../storage/secure_storage.dart';

class AuthInterceptor extends Interceptor {
  bool _refreshing = false;
  final List<_QueuedRequest> _queue = [];

  @override
  Future<void> onRequest(
    RequestOptions options,
    RequestInterceptorHandler handler,
  ) async {
    final token = await SecureStorage.getAccessToken();
    if (token != null && token.isNotEmpty) {
      options.headers['Authorization'] = 'Bearer $token';
    }
    handler.next(options);
  }

  @override
  Future<void> onError(
    DioException err,
    ErrorInterceptorHandler handler,
  ) async {
    if (err.response?.statusCode != 401) {
      return handler.next(err);
    }

    final refresh = await SecureStorage.getRefreshToken();
    if (refresh == null) {
      return handler.next(err);
    }

    // Déjà en cours → mise en queue
    if (_refreshing) {
      _queue.add(_QueuedRequest(err.requestOptions, handler));
      return;
    }

    _refreshing = true;

    try {
      final publicDio = Dio(BaseOptions(baseUrl: err.requestOptions.baseUrl));
      final resp = await publicDio.post(
        '/api/v1/auth/refresh',
        data: {'refresh_token': refresh},
      );

      final newAccess  = resp.data['access_token']  as String;
      final newRefresh = resp.data['refresh_token'] as String;

      await SecureStorage.saveTokens(
        accessToken: newAccess,
        refreshToken: newRefresh,
      );

      // Rejouer la requête initiale
      err.requestOptions.headers['Authorization'] = 'Bearer $newAccess';
      final cloned = await publicDio.fetch(err.requestOptions);
      handler.resolve(cloned);

      // Rejouer la queue
      for (final item in _queue) {
        item.requestOptions.headers['Authorization'] = 'Bearer $newAccess';
        try {
          final resp = await publicDio.fetch(item.requestOptions);
          item.handler.resolve(resp);
        } catch (e) {
          item.handler.next(err);
        }
      }
      _queue.clear();
    } catch (_) {
      await SecureStorage.wipe();
      handler.next(err);
    } finally {
      _refreshing = false;
    }
  }
}

class _QueuedRequest {
  _QueuedRequest(this.requestOptions, this.handler);
  final RequestOptions requestOptions;
  final ErrorInterceptorHandler handler;
}
