import 'package:flutter/material.dart';
import 'package:provider/provider.dart';
import 'package:school_core/school_core.dart';

import '../children/link_requests_screen.dart';
import '../common.dart';

/// Identity, school, link requests, logout, about the software.
class ProfileScreen extends StatelessWidget {
  const ProfileScreen({super.key});

  @override
  Widget build(BuildContext context) {
    final auth = context.watch<AuthService>();
    final identity = auth.identity;
    if (identity == null) return const SizedBox.shrink();
    final membership = identity.current;
    return Scaffold(
      appBar: AppBar(title: const Text('Profil')),
      body: ListView(
        padding: const EdgeInsets.all(16),
        children: [
          Card(
            child: Padding(
              padding: const EdgeInsets.all(16),
              child: Column(
                children: [
                  CircleAvatar(
                    radius: 34,
                    backgroundColor: Tokens.primary,
                    child: Text(
                      identity.initials,
                      style: const TextStyle(color: Colors.white, fontSize: 22, fontWeight: FontWeight.w700),
                    ),
                  ),
                  const SizedBox(height: 10),
                  Text(identity.fullName, style: const TextStyle(fontSize: 20, fontWeight: FontWeight.w700)),
                  Text(identity.username, style: const TextStyle(color: Tokens.textSecondary)),
                ],
              ),
            ),
          ),
          const SizedBox(height: 12),
          Card(
            child: Column(
              children: [
                ListTile(
                  leading: const Icon(Icons.school_outlined),
                  title: const Text('Établissement'),
                  subtitle: Text(membership?.schoolName ?? '—'),
                ),
                ListTile(
                  leading: const Icon(Icons.badge_outlined),
                  title: const Text('Rôle'),
                  subtitle: Text((membership?.roles.contains('PARENT') ?? false) ? 'Parent' : '—'),
                ),
                ListTile(
                  key: const Key('profile.links'),
                  leading: const Icon(Icons.family_restroom),
                  title: const Text('Rattachements et parrainage'),
                  trailing: const Icon(Icons.chevron_right),
                  onTap: () => openScreen<void>(context, const LinkRequestsScreen()),
                ),
              ],
            ),
          ),
          const SizedBox(height: 20),
          OutlinedButton.icon(
            key: const Key('profile.logout'),
            style: OutlinedButton.styleFrom(
              foregroundColor: Tokens.error,
              side: const BorderSide(color: Tokens.error),
            ),
            onPressed: () => auth.logout(),
            icon: const Icon(Icons.logout),
            label: const Text('Se déconnecter'),
          ),
          const SizedBox(height: 28),
          const Center(child: SoftwareBrand(size: 18, subtitle: 'Application parent · version 0.1.0')),
          const SizedBox(height: 6),
          const Text(
            'Les documents officiels (bulletins, reçus…) portent l\'identité de votre établissement.',
            textAlign: TextAlign.center,
            style: TextStyle(color: Tokens.textSecondary, fontSize: 12.5),
          ),
        ],
      ),
    );
  }
}
