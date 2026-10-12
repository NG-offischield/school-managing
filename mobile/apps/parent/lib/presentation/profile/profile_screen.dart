import 'package:flutter/material.dart';
import 'package:provider/provider.dart';
import 'package:school_core/school_core.dart';

import '../children/link_requests_screen.dart';
import '../common.dart';

/// Identity, school, link requests, school plan, logout, about the software.
class ProfileScreen extends StatelessWidget {
  const ProfileScreen({super.key});

  @override
  Widget build(BuildContext context) {
    final auth = context.watch<AuthService>();
    final identity = auth.identity;
    if (identity == null) return const SizedBox.shrink();
    final membership = identity.current;
    return Scaffold(
      appBar: AppBar(title: Text(tr('Profil'))),
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
                      style: TextStyle(color: Tokens.onPrimary, fontSize: 22, fontWeight: FontWeight.w700),
                    ),
                  ),
                  const SizedBox(height: 10),
                  Text(identity.fullName, style: const TextStyle(fontSize: 20, fontWeight: FontWeight.w700)),
                  Text(identity.username, style: TextStyle(color: Tokens.textSecondary)),
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
                  title: Text(tr('Établissement')),
                  subtitle: Text(membership?.schoolName ?? '—'),
                ),
                ListTile(
                  leading: const Icon(Icons.badge_outlined),
                  title: Text(tr('Rôle')),
                  subtitle: Text((membership?.roles.contains('PARENT') ?? false) ? tr('Parent') : '—'),
                ),
                ListTile(
                  key: const Key('profile.links'),
                  leading: const Icon(Icons.family_restroom),
                  title: Text(tr('Rattachements et parrainage')),
                  trailing: const Icon(Icons.chevron_right),
                  onTap: () => openScreen<void>(context, const LinkRequestsScreen()),
                ),
                ListTile(
                  key: const Key('profile.plans'),
                  leading: const Icon(Icons.map_outlined),
                  title: Text(tr('Plan de l\'établissement')),
                  subtitle: Text(tr('Bâtiments, salles et accès')),
                  trailing: const Icon(Icons.chevron_right),
                  onTap: () => Navigator.of(context).push(MaterialPageRoute<void>(builder: (_) => const PlansScreen())),
                ),
              ],
            ),
          ),
          Card(
            child: ListTile(
              key: const Key('profile.account'),
              leading: const Icon(Icons.manage_accounts_outlined),
              title: Text(tr('Mon compte et paramètres')),
              subtitle: Text(tr('Photo, coordonnées, mot de passe, appareils')),
              trailing: const Icon(Icons.chevron_right),
              onTap: () => Navigator.of(context).push(MaterialPageRoute<void>(builder: (_) => const AccountScreen())),
            ),
          ),
          // Server of the school (another network = another address, no rebuild).
          const ServerSettingsTile(),
          const SizedBox(height: 20),
          OutlinedButton.icon(
            key: const Key('profile.logout'),
            style: OutlinedButton.styleFrom(
              foregroundColor: Tokens.error,
              side: BorderSide(color: Tokens.error),
            ),
            onPressed: () => auth.logout(),
            icon: const Icon(Icons.logout),
            label: Text(tr('Se déconnecter')),
          ),
          const SizedBox(height: 28),
          Center(child: SoftwareBrand(size: 18, subtitle: tr('Application parent · version 0.1.0'))),
          const SizedBox(height: 6),
          Text(
            tr('Les documents officiels (bulletins, reçus…) portent l\'identité de votre établissement.'),
            textAlign: TextAlign.center,
            style: TextStyle(color: Tokens.textSecondary, fontSize: 12.5),
          ),
        ],
      ),
    );
  }
}
