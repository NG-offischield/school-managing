import 'package:flutter/material.dart';
import 'package:provider/provider.dart';
import 'package:school_core/school_core.dart';

/// Identity, school, school plan, logout, about the software.
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
                  subtitle: Text((membership?.roles.contains('TEACHER') ?? false) ? 'Enseignant' : '—'),
                ),
                ListTile(
                  key: const Key('profile.plans'),
                  leading: const Icon(Icons.map_outlined),
                  title: const Text("Plan de l'établissement"),
                  subtitle: const Text('Bâtiments, salles et accès'),
                  trailing: const Icon(Icons.chevron_right),
                  onTap: () => Navigator.of(context).push(MaterialPageRoute<void>(builder: (_) => const PlansScreen())),
                ),
              ],
            ),
          ),
          // Server of the school (another network = another address, no rebuild).
          const ServerSettingsTile(),
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
          const Center(child: SoftwareBrand(size: 18, subtitle: 'Application enseignant · version 0.1.0')),
          const SizedBox(height: 6),
          const Text(
            'Les documents officiels (bulletins, emplois du temps…) portent l\'identité de votre établissement.',
            textAlign: TextAlign.center,
            style: TextStyle(color: Tokens.textSecondary, fontSize: 12.5),
          ),
        ],
      ),
    );
  }
}
