/// « Mon compte »: what a member may manage about themself. The server decides
/// which fields are editable (`editable`); identity, login, role and school
/// stay with the administration.
///
///   GET/PATCH auth/me/profile/      GET/POST/DELETE auth/me/photo/
///   POST auth/password/change/ {current_password, new_password}   (other devices disconnected)
///   GET auth/sessions/   POST auth/sessions/{id}/revoke/   POST auth/sessions/revoke-all/
library;

import 'dart:typed_data';

import '../api/api_client.dart';
import '../api/api_error.dart';
import 'communication.dart';

/// Labels of the self-service fields (server names).
const accountFieldLabels = {
  'phone': 'Téléphone',
  'occupation': 'Profession',
  'address': 'Adresse',
  'emergency_phone': 'Téléphone d\'urgence',
  'preferred_language': 'Langue préférée',
};

const roleLabels = {
  'PARENT': 'Parent',
  'TEACHER': 'Enseignant',
  'STAFF': 'Personnel',
  'GUARDIAN': 'Gardien',
  'ADMIN': 'Administrateur',
  'SUPER_ADMIN': 'Super-administrateur',
};

class AccountProfile {
  AccountProfile({
    required this.firstName,
    required this.lastName,
    required this.email,
    required this.username,
    required this.schoolName,
    required this.roles,
    required this.hasPhoto,
    required this.values,
    required this.editable,
    required this.languages,
  });

  factory AccountProfile.fromJson(Map<String, dynamic> json) {
    final values = <String, String>{'phone': (json['phone'] as String?) ?? ''};
    for (final group in ['parent', 'employee']) {
      final map = (json[group] as Map?)?.cast<String, dynamic>();
      map?.forEach((key, value) => values[key] = '${value ?? ''}');
    }
    return AccountProfile(
      firstName: (json['first_name'] as String?) ?? '',
      lastName: (json['last_name'] as String?) ?? '',
      email: (json['email'] as String?) ?? '',
      username: (json['username'] as String?) ?? '',
      schoolName: (json['school_name'] as String?) ?? '',
      roles: ((json['roles'] as List?) ?? const []).map((r) => '$r').toList(),
      hasPhoto: json['has_photo'] == true,
      values: values,
      editable: ((json['editable'] as List?) ?? const []).map((f) => '$f').toList(),
      languages: ((json['languages'] as Map?) ?? const {}).map((k, v) => MapEntry('$k', '$v')),
    );
  }

  final String firstName;
  final String lastName;
  final String email;
  final String username;
  final String schoolName;
  final List<String> roles;
  final bool hasPhoto;

  /// Current value of every self-service field ('' when empty).
  final Map<String, String> values;

  /// Fields THIS member may change, in display order (decided by the server).
  final List<String> editable;

  /// preferred_language choices (parents only).
  final Map<String, String> languages;

  String get fullName => '$firstName $lastName'.trim();
  String get rolesLabel => roles.map((r) => roleLabels[r] ?? r).join(', ');
}

class UserSession {
  UserSession({
    required this.id,
    required this.deviceName,
    required this.platform,
    required this.current,
    this.lastUsedAt,
    this.ip,
  });

  factory UserSession.fromJson(Map<String, dynamic> json) => UserSession(
    id: '${json['id']}',
    deviceName: (json['device_name'] as String?) ?? 'Appareil',
    platform: (json['platform'] as String?) ?? '',
    current: json['is_current'] == true,
    lastUsedAt: schoolTime(json['last_used_at'] ?? json['created_at']),
    ip: json['ip_address'] as String?,
  );

  final String id;
  final String deviceName;
  final String platform;
  final bool current;
  final DateTime? lastUsedAt;
  final String? ip;
}

class AccountRepository {
  AccountRepository(this.api);

  final ApiClient api;

  Future<AccountProfile> profile() async =>
      AccountProfile.fromJson((await api.get('auth/me/profile/') as Map).cast<String, dynamic>());

  /// Only the changed fields are sent; the server refuses any other field.
  Future<AccountProfile> update(Map<String, String> changes) async =>
      AccountProfile.fromJson((await api.patch('auth/me/profile/', body: changes) as Map).cast<String, dynamic>());

  /// The photo (JPEG made by the server), null when there is none.
  Future<Uint8List?> photo() async {
    try {
      return await api.download('auth/me/photo/');
    } on NotFoundException {
      return null;
    }
  }

  Future<AccountProfile> uploadPhoto(Uint8List bytes) async => AccountProfile.fromJson(
    (await api.upload('auth/me/photo/', field: 'photo', filename: 'photo.jpg', bytes: bytes) as Map)
        .cast<String, dynamic>(),
  );

  Future<AccountProfile> deletePhoto() async =>
      AccountProfile.fromJson(((await api.request('DELETE', 'auth/me/photo/')).data as Map).cast<String, dynamic>());

  Future<void> changePassword(String current, String next) =>
      api.post('auth/password/change/', body: {'current_password': current, 'new_password': next});

  Future<List<UserSession>> sessions() async => ((await api.get('auth/sessions/') as List?) ?? const [])
      .map((r) => UserSession.fromJson((r as Map).cast<String, dynamic>()))
      .toList();

  Future<void> revokeSession(String id) => api.post('auth/sessions/$id/revoke/');

  /// Every session, THIS one included: the caller must then sign out locally.
  Future<int> revokeAll() async =>
      ((await api.post('auth/sessions/revoke-all/') as Map?)?['revoked_count'] as int?) ?? 0;
}
