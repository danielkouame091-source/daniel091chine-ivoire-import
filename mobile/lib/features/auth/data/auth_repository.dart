import 'package:dio/dio.dart';

import '../../../core/network/api_client.dart';
import '../../../core/storage/secure_storage.dart';
import 'models/user.dart';

class AuthRepository {
  AuthRepository(this._dio);
  final Dio _dio;

  Future<AuthTokens> login({
    required String email,
    required String password,
  }) async {
    final response = await _dio.post(
      '/api/v1/auth/login',
      data: {'email': email, 'password': password},
    );

    final tokens = AuthTokens.fromJson(response.data);

    if (!tokens.mfaRequired && tokens.accessToken.isNotEmpty) {
      await SecureStorage.saveTokens(
        accessToken: tokens.accessToken,
        refreshToken: tokens.refreshToken,
      );
    }
    return tokens;
  }

  Future<AuthTokens> verifyMfa({
    required String email,
    required String code,
    required String sessionToken,
  }) async {
    final response = await _dio.post(
      '/api/v1/auth/mfa/verify',
      data: {'email': email, 'code': code, 'session_token': sessionToken},
    );

    final tokens = AuthTokens.fromJson(response.data);
    await SecureStorage.saveTokens(
      accessToken: tokens.accessToken,
      refreshToken: tokens.refreshToken,
    );
    return tokens;
  }

  Future<User> me() async {
    final response = await _dio.get('/api/v1/auth/me');
    final user = User.fromJson(response.data);
    await SecureStorage.saveUserId(user.id);
    if (user.tenantId != null) {
      await SecureStorage.saveTenantId(user.tenantId!);
    }
    return user;
  }

  Future<void> logout() async {
    try {
      await _dio.post('/api/v1/auth/logout');
    } catch (_) {}
    await SecureStorage.clearTokens();
  }
}
