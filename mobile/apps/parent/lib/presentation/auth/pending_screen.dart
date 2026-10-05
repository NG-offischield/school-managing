import 'package:flutter/material.dart';
import 'package:provider/provider.dart';
import 'package:school_core/school_core.dart';

import '../../data/parent_repository.dart';
import '../../models/models.dart';
import '../common.dart';

/// Signed in, but the account still waits for the school (membership
/// PENDING): only the registration state is shown — the server grants
/// nothing of the school meanwhile.
class PendingScreen extends StatefulWidget {
  const PendingScreen({super.key});

  @override
  State<PendingScreen> createState() => _PendingScreenState();
}

class _PendingScreenState extends State<PendingScreen> {
  Future<List<Registration>>? _future;
  String? _error;

  @override
  void initState() {
    super.initState();
    _load();
  }

  void _load() => setState(() {
    _future = context.read<ParentRepository>().registrations()..ignore();
  });

  Future<void> _check() async {
    final auth = context.read<AuthService>();
    try {
      await auth.reloadIdentity(); // approved -> the gate opens the home
      if (mounted) _load();
    } on WrongRoleException {
      await auth.expire('Ce compte n\'est pas un compte parent.');
    } on ApiException catch (error) {
      if (mounted) setState(() => _error = error.userMessage);
    }
  }

  @override
  Widget build(BuildContext context) {
    final auth = context.watch<AuthService>();
    return Scaffold(
      appBar: AppBar(
        title: const Text('Mon compte'),
        actions: [
          IconButton(
            key: const Key('pending.logout'),
            tooltip: 'Se déconnecter',
            icon: const Icon(Icons.logout),
            onPressed: auth.logout,
          ),
        ],
      ),
      body: AsyncBody<List<Registration>>(
        future: _future,
        onRetry: _load,
        builder: (context, rows) {
          final last = rows.isEmpty ? null : rows.first;
          final rejected = last?.status == 'REJECTED';
          return ListView(
            padding: const EdgeInsets.all(20),
            children: [
              const SoftwareBrand(subtitle: 'Espace parent'),
              const SizedBox(height: 24),
              if (_error != null) ...[MessageBanner(_error!), const SizedBox(height: 12)],
              Card(
                child: Padding(
                  padding: const EdgeInsets.all(18),
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Row(
                        children: [
                          Icon(
                            rejected ? Icons.block : Icons.hourglass_top_rounded,
                            color: rejected ? Tokens.error : Tokens.warning,
                          ),
                          const SizedBox(width: 10),
                          Expanded(
                            child: Text(
                              'Bonjour ${auth.identity?.firstName ?? ''}',
                              style: const TextStyle(fontSize: 18, fontWeight: FontWeight.w700),
                            ),
                          ),
                        ],
                      ),
                      const SizedBox(height: 12),
                      Text(
                        rejected
                            ? 'Votre demande a été refusée par l\'établissement.'
                            : 'Votre compte attend la validation de l\'établissement'
                                  '${last == null ? '' : ' (${last.schoolName})'}.',
                      ),
                      if (last?.submittedAt != null) ...[
                        const SizedBox(height: 6),
                        Text(
                          'Demande du ${dateTime.format(last!.submittedAt!)}',
                          style: const TextStyle(color: Tokens.textSecondary),
                        ),
                      ],
                      if (rejected && (last?.rejectionReason ?? '').isNotEmpty) ...[
                        const SizedBox(height: 6),
                        Text('Motif : ${last!.rejectionReason}'),
                      ],
                      const SizedBox(height: 10),
                      StatusChip(last?.statusLabel ?? 'En attente', tone: rejected ? Tone.danger : Tone.warning),
                    ],
                  ),
                ),
              ),
              const SizedBox(height: 16),
              const Text(
                'Une fois le compte validé, vous demanderez le rattachement de votre enfant : la pièce d\'identité '
                'indiquée sera vérifiée à l\'école. Aucune donnée d\'élève n\'est visible avant.',
                style: TextStyle(color: Tokens.textSecondary),
              ),
              const SizedBox(height: 20),
              if (!rejected)
                FilledButton.icon(
                  key: const Key('pending.check'),
                  onPressed: _check,
                  icon: const Icon(Icons.refresh),
                  label: const Text('Vérifier la validation'),
                ),
            ],
          );
        },
      ),
    );
  }
}
