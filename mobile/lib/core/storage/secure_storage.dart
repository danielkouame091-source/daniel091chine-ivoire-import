import 'package:flutter_secure_storage/flutter_secure_storage.dart';

class SecureStorage {
  static const _storage = FlutterSecureStorage(
    aOptions: AndroidOptions(encryptedSharedPreferences: true),
    iOptions: IOSOptions(accessibility: KeychainAccessibility.first_unlock),
  );

  // Clés
  static const _kAccessToken  = 'access_token';
  static const _kRefreshToken = 'refresh_token';
  static const _kUserId       = 'user_id';
  static const _kTenantId     = 'tenant_id';
  static const _kBiometricOn  = 'biometric_enabled';

  // ─── Tokens ────────────────────────────────────────────
  static Future<void> saveTokens({
    required String accessToken,
    required String refreshToken,
  }) async {
    await _storage.write(key: _kAccessToken, value: accessToken);
    await _storage.write(key: _kRefreshToken, value: refreshToken);
  }

  static Future<String?> getAccessToken()  => _storage.read(key: _kAccessToken);
  static Future<String?> getRefreshToken() => _storage.read(key: _kRefreshToken);

  static Future<void> clearTokens() async {
    await _storage.delete(key: _kAccessToken);
    await _storage.delete(key: _kRefreshToken);
  }

  // ─── Identifiants ──────────────────────────────────────
  static Future<void> saveUserId(String id)   => _storage.write(key: _kUserId, value: id);
  static Future<String?> getUserId()          => _storage.read(key: _kUserId);
  static Future<void> saveTenantId(String id) => _storage.write(key: _kTenantId, value: id);
  static Future<String?> getTenantId()        => _storage.read(key: _kTenantId);

  // ─── Biométrie ─────────────────────────────────────────
  static Future<void> setBiometric(bool enabled) =>
      _storage.write(key: _kBiometricOn, value: enabled ? 'true' : 'false');
  static Future<bool> isBiometricEnabled() async {
    final v = await _storage.read(key: _kBiometricOn);
    return v == 'true';
  }

  // ─── Nuke (logout) ─────────────────────────────────────
  static Future<void> wipe() => _storage.deleteAll();
}
