/// The connected person, as returned by `GET /auth/me/`.
library;

class Membership {
  Membership({
    required this.id,
    required this.schoolCode,
    required this.schoolName,
    required this.status,
    required this.isPrimary,
    required this.roles,
  });

  factory Membership.fromJson(Map<String, dynamic> json) => Membership(
    id: '${json['id']}',
    schoolCode: (json['school_code'] as String?) ?? '',
    schoolName: (json['school_name'] as String?) ?? '',
    status: (json['status'] as String?) ?? '',
    isPrimary: json['is_primary_school'] == true,
    roles: ((json['roles'] as List?) ?? const []).map((e) => '$e').toSet(),
  );

  final String id;
  final String schoolCode;
  final String schoolName;
  final String status;
  final bool isPrimary;
  final Set<String> roles;

  bool get active => status == 'ACTIVE';
}

class Identity {
  Identity({
    required this.userId,
    required this.username,
    required this.firstName,
    required this.lastName,
    required this.memberships,
  });

  factory Identity.fromMe(Map<String, dynamic> json) => Identity(
    userId: '${json['id']}',
    username: (json['username'] as String?) ?? '',
    firstName: (json['first_name'] as String?) ?? '',
    lastName: (json['last_name'] as String?) ?? '',
    memberships: ((json['memberships'] as List?) ?? const [])
        .map((m) => Membership.fromJson((m as Map).cast<String, dynamic>()))
        .toList(),
  );

  final String userId;
  final String username;
  final String firstName;
  final String lastName;
  final List<Membership> memberships;

  String get fullName => '$firstName $lastName'.trim().isEmpty ? username : '$firstName $lastName'.trim();

  String get initials {
    final letters = [firstName, lastName].where((p) => p.isNotEmpty).map((p) => p[0].toUpperCase()).join();
    return letters.isEmpty ? '?' : letters;
  }

  /// The school the server resolves for this user: the primary ACTIVE
  /// membership, or the only ACTIVE one (same rule as the backend).
  Membership? get current {
    final active = memberships.where((m) => m.active).toList();
    final primary = active.where((m) => m.isPrimary).toList();
    if (primary.length == 1) return primary.single;
    return active.length == 1 ? active.single : null;
  }

  bool hasRole(String role) => current?.roles.contains(role) ?? false;
}
