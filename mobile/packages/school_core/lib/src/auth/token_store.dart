/// Where the session survives an app restart: ONLY the refresh token and the
/// install identifier, in the platform's secure storage (Android Keystore).
/// Never a password, never the access token, never an activation code.
library;

import 'dart:math';

import 'package:flutter_secure_storage/flutter_secure_storage.dart';

abstract class TokenStore {
  Future<String?> readRefreshToken();
  Future<void> writeRefreshToken(String token);
  Future<void> deleteRefreshToken();

  /// Stable per-install identifier sent at login (hashed by the server).
  Future<String> deviceIdentifier();
}

String newDeviceIdentifier() {
  final random = Random.secure();
  return List.generate(16, (_) => random.nextInt(256).toRadixString(16).padLeft(2, '0')).join();
}

class SecureTokenStore implements TokenStore {
  SecureTokenStore({FlutterSecureStorage? storage, this.prefix = 'school_managing'})
    : _storage = storage ?? const FlutterSecureStorage();

  final FlutterSecureStorage _storage;
  final String prefix;

  String get _refreshKey => '$prefix.refresh_token';
  String get _deviceKey => '$prefix.device_identifier';

  @override
  Future<String?> readRefreshToken() => _storage.read(key: _refreshKey);

  @override
  Future<void> writeRefreshToken(String token) => _storage.write(key: _refreshKey, value: token);

  @override
  Future<void> deleteRefreshToken() => _storage.delete(key: _refreshKey);

  @override
  Future<String> deviceIdentifier() async {
    final existing = await _storage.read(key: _deviceKey);
    if (existing != null && existing.isNotEmpty) return existing;
    final created = newDeviceIdentifier();
    await _storage.write(key: _deviceKey, value: created);
    return created;
  }
}

/// In-memory store (tests, or a device without secure storage: the session
/// then simply does not survive a restart).
class MemoryTokenStore implements TokenStore {
  String? refreshToken;
  String? _device;

  @override
  Future<String?> readRefreshToken() async => refreshToken;

  @override
  Future<void> writeRefreshToken(String token) async => refreshToken = token;

  @override
  Future<void> deleteRefreshToken() async => refreshToken = null;

  @override
  Future<String> deviceIdentifier() async => _device ??= newDeviceIdentifier();
}
