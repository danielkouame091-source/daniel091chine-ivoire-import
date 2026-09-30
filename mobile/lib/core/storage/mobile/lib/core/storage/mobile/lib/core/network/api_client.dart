import 'package:dio/dio.dart';
import 'package:flutter/foundation.dart';

import '../config/env.dart';
import '../storage/secure_storage.dart';
import 'auth_interceptor.dart';
import 'error_interceptor.dart';
import 'logging_interceptor.dart';

class ApiClient {
  static late final Dio _dio;
  static late final Dio _publicDio;

  static Dio get dio => _dio;
  static Dio get publicDio => _publicDio;

  static void init() {
    // ─── API principale (authentifiée) ──────────────────
    _dio = Dio(BaseOptions(
      baseUrl: Env.apiUrl,
      connectTimeout: const Duration(seconds: 15),
      receiveTimeout: const Duration(seconds: 30),
      sendTimeout: const Duration(seconds: 30),
      headers: {
        'Accept': 'application/json',
        'Content-Type': 'application/json',
        'X-Client': 'mtech-mobile',
        'X-Client-Version': Env.appVersion,
        'X-Client-Platform': defaultTargetPlatform.name,
      },
    ));

    // ─── API publique (sans auth pour login/refresh) ────
    _publicDio = Dio(BaseOptions(
      baseUrl: Env.apiUrl,
      connectTimeout: const Duration(seconds: 15),
      receiveTimeout: const Duration(seconds: 30),
      headers: {
        'Accept': 'application/json',
        'Content-Type': 'application/json',
        'X-Client': 'mtech-mobile',
      },
    ));

    // ─── Interceptors ordre critique ────────────────────
    _dio.interceptors.addAll([
      AuthInterceptor(),        // Ajoute Bearer token + refresh auto
      ErrorInterceptor(),       // Transforme les erreurs en ApiException
      if (Env.isDev) LoggingInterceptor(),
    ]);

    _publicDio.interceptors.addAll([
      ErrorInterceptor(),
      if (Env.isDev) LoggingInterceptor(),
    ]);
  }
}

class ApiException implements Exception {
  ApiException({
    required this.statusCode,
    required this.code,
    required this.message,
    this.details,
  });

  final int statusCode;
  final String code;
  final String message;
  final Map<String, dynamic>? details;

  bool get isUnauthorized   => statusCode == 401;
  bool get isForbidden      => statusCode == 403;
  bool get isNotFound       => statusCode == 404;
  bool get isExpired        => statusCode == 402; // SUBSCRIPTION_EXPIRED
  bool get isRateLimited    => statusCode == 429;
  bool get isServerError    => statusCode >= 500;

  @override
  String toString() => 'ApiException($statusCode, $code) : $message';
}
