/// Session of the connected person, built ONLY on the backend's sessions
/// (ADR 0002) — no local authentication:
///
///   login      POST /auth/login/  {identifier, password, device}
///   refresh    POST /auth/refresh/ {refresh_token}   (rotation; a reused token
///              revokes the session server-side)
///   logout     POST /auth/logout/
///   identity   GET  /auth/me/
///   activation POST /auth/activation/check/ {code}
///              POST /auth/activation/complete/ {code, password}   (ADR 0024)
///
/// The password is sent once and never kept. Only the refresh token is
/// stored (secure storage); the access token stays in memory.
library;

import 'package:flutter/foundation.dart';

import '../api/api_client.dart';
import '../api/api_error.dart';
import 'identity.dart';
import 'token_store.dart';

enum AuthStatus { restoring, signedOut, signedIn }

class DeviceInfo {
  const DeviceInfo({
    this.name = 'Téléphone',
    this.type = 'PHONE',
    this.platform = 'ANDROID',
    this.appVersion = '0.1.0',
  });

  final String name;
  final String type;
  final String platform;
  final String appVersion;
}

class ActivationPreview {
  ActivationPreview({required this.firstName, required this.school, required this.login, this.expiresAt});

  final String firstName;
  final String school;
  final String login;
  final DateTime? expiresAt;
}

/// Login refused because this app is for another role (e.g. a parent
/// account opening the teacher app). The session is closed at once.
class WrongRoleException implements Exception {
  WrongRoleException(this.role);

  final String role;
}

class AuthService extends ChangeNotifier {
  AuthService(this.api, this.store, {this.device = const DeviceInfo(), this.requiredRole}) {
    api.refreshHandler = _refreshQuietly;
  }

  final ApiClient api;
  final TokenStore store;
  final DeviceInfo device;

  /// Role the app is made for (e.g. TEACHER); null = any member.
  final String? requiredRole;

  AuthStatus status = AuthStatus.restoring;
  Identity? identity;

  /// Why the user is back on the login screen (expired session...).
  String? notice;

  bool get signedIn => status == AuthStatus.signedIn;

  /// Resume the remembered session, if any (app start).
  Future<void> restore() async {
    final refresh = await store.readRefreshToken();
    if (refresh == null) {
      _signedOut();
      return;
    }
    try {
      await _renew(refresh);
      await _loadIdentity();
    } on NetworkException {
      // Offline at start: keep the stored session, let the user retry.
      _signedOut(notice: 'Serveur injoignable : vérifiez votre connexion puis reconnectez-vous.');
      return;
    } on ApiException {
      await store.deleteRefreshToken();
      _signedOut(notice: 'Votre session a expiré : reconnectez-vous.');
    } on WrongRoleException {
      _signedOut(notice: 'Ce compte n\'a pas accès à cette application.');
    }
  }

  Future<void> login(String identifier, String password) async {
    final data =
        await api.post(
              'auth/login/',
              auth: false,
              body: {
                'identifier': identifier.trim(),
                'password': password,
                'device': {
                  'identifier': await store.deviceIdentifier(),
                  'device_name': device.name,
                  'device_type': device.type,
                  'platform': device.platform,
                  'app_version': device.appVersion,
                },
              },
            )
            as Map<String, dynamic>;
    await _keep(data);
    await _loadIdentity();
  }

  Future<ActivationPreview> checkActivation(String code) async {
    final data = await api.post('auth/activation/check/', auth: false, body: {'code': code.trim()}) as Map;
    return ActivationPreview(
      firstName: (data['first_name'] as String?) ?? '',
      school: (data['school'] as String?) ?? '',
      login: (data['login'] as String?) ?? '',
      expiresAt: DateTime.tryParse('${data['expires_at']}'),
    );
  }

  /// Sets the FIRST password (the server validates its strength and burns
  /// the code). Returns the login identifier to use.
  Future<String> completeActivation(String code, String password) async {
    final data =
        await api.post('auth/activation/complete/', auth: false, body: {'code': code.trim(), 'password': password})
            as Map;
    return (data['login'] as String?) ?? '';
  }

  Future<void> logout() async {
    try {
      if (api.accessToken != null) await api.post('auth/logout/');
    } on ApiException {
      // Already revoked / offline: the local session is closed anyway.
    }
    await _clear();
    _signedOut(notice: 'Vous êtes déconnecté.');
  }

  /// Session refused by the server (refresh failed, suspended account...).
  Future<void> expire([String message = 'Votre session a expiré : reconnectez-vous.']) async {
    await _clear();
    _signedOut(notice: message);
  }

  /// One refresh of the access token (e.g. after the WebSocket was closed
  /// with 4401). A refused refresh expires the session.
  Future<bool> refreshSession() => _refreshQuietly();

  // --- internals ---------------------------------------------------------------------

  Future<void> _keep(Map<String, dynamic> tokens) async {
    api.accessToken = tokens['access_token'] as String?;
    await store.writeRefreshToken(tokens['refresh_token'] as String);
  }

  Future<void> _renew(String refresh) async {
    final data = await api.post('auth/refresh/', auth: false, body: {'refresh_token': refresh}) as Map<String, dynamic>;
    await _keep(data);
  }

  Future<bool> _refreshQuietly() async {
    final refresh = await store.readRefreshToken();
    if (refresh == null) return false;
    try {
      await _renew(refresh);
      return true;
    } on NetworkException {
      return false;
    } on ApiException {
      await expire();
      return false;
    }
  }

  Future<void> _loadIdentity() async {
    final me = Identity.fromMe((await api.get('auth/me/') as Map).cast<String, dynamic>());
    if (me.current == null) {
      await _clear();
      throw ForbiddenException(code: 'NO_ACTIVE_MEMBERSHIP', message: 'No active membership.');
    }
    final role = requiredRole;
    if (role != null && !me.hasRole(role)) {
      try {
        await api.post('auth/logout/');
      } on ApiException {
        // ignore: the session is dropped locally anyway
      }
      await _clear();
      throw WrongRoleException(role);
    }
    identity = me;
    notice = null;
    status = AuthStatus.signedIn;
    notifyListeners();
  }

  Future<void> _clear() async {
    api.accessToken = null;
    identity = null;
    await store.deleteRefreshToken();
  }

  void _signedOut({String? notice}) {
    status = AuthStatus.signedOut;
    this.notice = notice;
    notifyListeners();
  }
}
