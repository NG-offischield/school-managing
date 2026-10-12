import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:provider/provider.dart';
import 'package:school_core/school_core.dart';

import '../../data/parent_repository.dart';
import '../../models/models.dart';
import '../common.dart';

/// Rattachements (spec §6.5): « this is my child » requests and their
/// progress (identity checked at the school, the pupil's designation, the
/// school's decision), the sponsor code of a second parent, and — for a
/// verified parent — issuing such a code. Every check is the server's:
/// nothing here grants access to a child.
class LinkRequestsScreen extends StatefulWidget {
  const LinkRequestsScreen({super.key});

  @override
  State<LinkRequestsScreen> createState() => _LinkRequestsScreenState();
}

class _LinkRequestsScreenState extends State<LinkRequestsScreen> {
  Future<List<LinkRequest>>? _future;

  @override
  void initState() {
    super.initState();
    _load();
  }

  void _load() {
    setState(() {
      _future = context.read<ParentRepository>().linkRequests()..ignore();
    });
  }

  Future<void> _new() async {
    final created = await openScreen<LinkRequest>(context, const LinkRequestForm());
    if (created != null && mounted) {
      showMessage(context, 'Demande envoyée : présentez votre pièce d\'identité à l\'école.');
      _load();
    }
  }

  Future<void> _sponsor(LinkRequest request) async {
    final repo = context.read<ParentRepository>();
    final code = await showDialog<String>(context: context, builder: (_) => const _SponsorCodeDialog());
    if (code == null || code.trim().isEmpty || !mounted) return;
    try {
      await repo.sponsor(request.id, code);
      if (mounted) showMessage(context, 'Parrainage accepté : l\'école finalisera le rattachement.');
    } on ApiException catch (error) {
      if (mounted) showMessage(context, error.userMessage);
    }
    if (mounted) _load();
  }

  Future<void> _cancel(LinkRequest request) async {
    final repo = context.read<ParentRepository>();
    try {
      await repo.cancelRequest(request.id);
      if (mounted) showMessage(context, 'Demande annulée.');
    } on ApiException catch (error) {
      if (mounted) showMessage(context, error.userMessage);
    }
    if (mounted) _load();
  }

  Future<void> _issueCode(Child child) async {
    try {
      final code = await context.read<ParentRepository>().sponsorCode(child.id);
      if (!mounted) return;
      await showDialog<void>(
        context: context,
        builder: (_) => _IssuedCodeDialog(child: child, code: code),
      );
    } on ApiException catch (error) {
      if (mounted) showMessage(context, error.userMessage);
    }
  }

  Tone _tone(String status) => switch (status) {
    'APPROVED' => Tone.success,
    'REJECTED' => Tone.danger,
    'PENDING' => Tone.warning,
    _ => Tone.neutral,
  };

  @override
  Widget build(BuildContext context) {
    final children = context.watch<ChildScope>().children;
    return Scaffold(
      appBar: AppBar(title: const Text('Rattachements')),
      floatingActionButton: FloatingActionButton.extended(
        key: const Key('link.new'),
        onPressed: _new,
        icon: const Icon(Icons.add),
        label: const Text('Rattacher un enfant'),
      ),
      body: AsyncBody<List<LinkRequest>>(
        future: _future,
        onRetry: _load,
        builder: (context, rows) => RefreshIndicator(
          onRefresh: () async {
            _load();
            await _future?.catchError((_) => <LinkRequest>[]);
          },
          child: ListView(
            padding: const EdgeInsets.fromLTRB(16, 8, 16, 96),
            children: [
              Text(
                'Pour voir la scolarité d\'un enfant, votre lien doit être vérifié : l\'école contrôle votre pièce '
                'd\'identité (ou un parent déjà vérifié vous parraine avec un code), l\'élève confirme, puis '
                'l\'établissement valide.',
                style: TextStyle(color: Tokens.textSecondary),
              ),
              const SectionTitle('Mes demandes'),
              if (rows.isEmpty)
                Padding(
                  padding: EdgeInsets.all(8),
                  child: Text('Aucune demande.', style: TextStyle(color: Tokens.textSecondary)),
                ),
              for (final r in rows)
                Card(
                  child: Padding(
                    padding: const EdgeInsets.all(14),
                    child: Column(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        Row(
                          children: [
                            Expanded(
                              child: Text(r.studentName, style: const TextStyle(fontWeight: FontWeight.w700)),
                            ),
                            StatusChip(r.statusLabel, tone: _tone(r.status)),
                          ],
                        ),
                        const SizedBox(height: 6),
                        InfoRow('Lien', relationships[r.relationship] ?? r.relationship),
                        InfoRow('Identité', r.identityLabel),
                        InfoRow('Désignation par l\'élève', r.approvalLabel),
                        if ((r.decisionReason ?? '').isNotEmpty) InfoRow('Motif', r.decisionReason!),
                        if (r.pending)
                          Wrap(
                            spacing: 8,
                            children: [
                              if (!r.sponsored)
                                TextButton.icon(
                                  key: Key('link.sponsor.${r.id}'),
                                  onPressed: () => _sponsor(r),
                                  icon: const Icon(Icons.key_outlined),
                                  label: const Text('J\'ai un code de parrainage'),
                                ),
                              TextButton(
                                key: Key('link.cancel.${r.id}'),
                                onPressed: () => _cancel(r),
                                child: const Text('Annuler la demande'),
                              ),
                            ],
                          ),
                      ],
                    ),
                  ),
                ),
              if (children.isNotEmpty) ...[
                const SectionTitle('Parrainer un second parent'),
                Text(
                  'Vous êtes parent vérifié : générez un code à usage unique (valable 10 minutes) et remettez-le en '
                  'main propre à l\'autre parent. L\'école validera son rattachement ; il n\'aura jamais plus de '
                  'droits financiers que vous.',
                  style: TextStyle(color: Tokens.textSecondary),
                ),
                for (final child in children)
                  Card(
                    child: Padding(
                      padding: const EdgeInsets.fromLTRB(16, 8, 12, 8),
                      child: Row(
                        children: [
                          Expanded(
                            child: Text(child.name, style: const TextStyle(fontWeight: FontWeight.w600)),
                          ),
                          OutlinedButton(
                            key: Key('sponsor.issue.${child.id}'),
                            // The theme's buttons are full width: sized to their label here.
                            style: OutlinedButton.styleFrom(minimumSize: const Size(0, 44)),
                            onPressed: () => _issueCode(child),
                            child: const Text('Générer un code'),
                          ),
                        ],
                      ),
                    ),
                  ),
              ],
            ],
          ),
        ),
      ),
    );
  }
}

class _SponsorCodeDialog extends StatefulWidget {
  const _SponsorCodeDialog();

  @override
  State<_SponsorCodeDialog> createState() => _SponsorCodeDialogState();
}

class _SponsorCodeDialogState extends State<_SponsorCodeDialog> {
  final _code = TextEditingController();

  @override
  void dispose() {
    _code.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    return AlertDialog(
      scrollable: true,
      title: const Text('Code de parrainage'),
      content: TextField(
        key: const Key('sponsor.code'),
        controller: _code,
        autofocus: true,
        textCapitalization: TextCapitalization.characters,
        decoration: const InputDecoration(
          labelText: 'Code remis par le parent vérifié',
          helperText: 'Format XXXX-XXXX, valable 10 minutes.',
        ),
      ),
      actions: [
        TextButton(onPressed: () => Navigator.of(context).pop(), child: const Text('Annuler')),
        FilledButton(
          key: const Key('sponsor.submit'),
          onPressed: () => Navigator.of(context).pop(_code.text),
          child: const Text('Valider'),
        ),
      ],
    );
  }
}

/// The code is shown ONCE (not stored by the app; the server keeps a hash).
class _IssuedCodeDialog extends StatelessWidget {
  const _IssuedCodeDialog({required this.child, required this.code});

  final Child child;
  final SponsorCode code;

  @override
  Widget build(BuildContext context) {
    return AlertDialog(
      scrollable: true,
      title: Text('Code pour ${child.firstName}'),
      content: Column(
        mainAxisSize: MainAxisSize.min,
        children: [
          SelectableText(
            code.code,
            key: const Key('sponsor.issued'),
            style: const TextStyle(fontSize: 30, fontWeight: FontWeight.w800, letterSpacing: 2),
          ),
          const SizedBox(height: 10),
          Text(
            'À remettre en main propre. Valable jusqu\'à '
            '${code.expiresAt == null ? '—' : hm.format(code.expiresAt!)}, une seule fois. '
            'Il ne sera plus affiché.',
            textAlign: TextAlign.center,
          ),
        ],
      ),
      actions: [
        TextButton(
          onPressed: () => Clipboard.setData(ClipboardData(text: code.code)),
          child: const Text('Copier'),
        ),
        FilledButton(onPressed: () => Navigator.of(context).pop(), child: const Text('Fermer')),
      ],
    );
  }
}

/// « This is my child »: pupil number + date of birth (both must match),
/// relationship, identity document — whose number is sent once and kept by
/// the server as an HMAC only, then checked against the ORIGINAL at school.
class LinkRequestForm extends StatefulWidget {
  const LinkRequestForm({super.key});

  @override
  State<LinkRequestForm> createState() => _LinkRequestFormState();
}

class _LinkRequestFormState extends State<LinkRequestForm> {
  final _number = TextEditingController();
  final _document = TextEditingController();
  DateTime? _birth;
  String _relationship = 'MOTHER';
  String _documentType = 'CNI';
  bool _busy = false;
  String? _error;

  @override
  void dispose() {
    _number.dispose();
    _document.dispose();
    super.dispose();
  }

  bool get _ready => !_busy && _number.text.trim().isNotEmpty && _birth != null && _document.text.trim().length >= 4;

  Future<void> _pickBirth() async {
    final now = DateTime.now();
    final picked = await showDatePicker(
      context: context,
      initialDate: _birth ?? DateTime(now.year - 10),
      firstDate: DateTime(now.year - 30),
      lastDate: now,
      helpText: 'Date de naissance de l\'enfant',
    );
    if (picked != null) setState(() => _birth = picked);
  }

  Future<void> _submit() async {
    if (!_ready) return;
    setState(() {
      _busy = true;
      _error = null;
    });
    try {
      final created = await context.read<ParentRepository>().requestLink(
        studentNumber: _number.text,
        dateOfBirth: _birth!,
        relationship: _relationship,
        documentType: _documentType,
        documentNumber: _document.text,
      );
      if (mounted) Navigator.of(context).pop(created);
    } on ApiException catch (error) {
      if (mounted) setState(() => _error = error.userMessage);
    } finally {
      _document.clear(); // never kept on the phone
      if (mounted) setState(() => _busy = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(title: const Text('Rattacher un enfant')),
      body: ListView(
        padding: const EdgeInsets.all(16),
        children: [
          if (_error != null) ...[MessageBanner(_error!), const SizedBox(height: 12)],
          const SectionTitle('L\'enfant'),
          TextField(
            key: const Key('link.number'),
            controller: _number,
            textCapitalization: TextCapitalization.characters,
            onChanged: (_) => setState(() {}),
            decoration: const InputDecoration(
              labelText: 'Matricule de l\'élève',
              helperText: 'Inscrit sur la carte ou un document scolaire.',
            ),
          ),
          const SizedBox(height: 12),
          OutlinedButton.icon(
            key: const Key('link.birth'),
            onPressed: _pickBirth,
            icon: const Icon(Icons.cake_outlined),
            label: Text(_birth == null ? 'Date de naissance' : 'Né(e) le ${dateOnly.format(_birth!)}'),
          ),
          const SizedBox(height: 12),
          DropdownButtonFormField<String>(
            isExpanded: true,
            key: const Key('link.relationship'),
            initialValue: _relationship,
            decoration: const InputDecoration(labelText: 'Votre lien avec l\'enfant'),
            items: [for (final e in relationships.entries) DropdownMenuItem(value: e.key, child: Text(e.value))],
            onChanged: (value) => setState(() => _relationship = value ?? 'MOTHER'),
          ),
          const SectionTitle('Votre pièce d\'identité'),
          DropdownButtonFormField<String>(
            isExpanded: true,
            initialValue: _documentType,
            decoration: const InputDecoration(labelText: 'Type de pièce'),
            items: [for (final e in documentTypes.entries) DropdownMenuItem(value: e.key, child: Text(e.value))],
            onChanged: (value) => setState(() => _documentType = value ?? 'CNI'),
          ),
          const SizedBox(height: 12),
          TextField(
            key: const Key('link.document'),
            controller: _document,
            autocorrect: false,
            enableSuggestions: false,
            onChanged: (_) => setState(() {}),
            decoration: const InputDecoration(
              labelText: 'Numéro de la pièce',
              helperText:
                  'Seule une empreinte chiffrée est conservée. Présentez la pièce originale à l\'école pour la '
                  'vérification.',
              helperMaxLines: 3,
            ),
          ),
          const SizedBox(height: 20),
          FilledButton(
            key: const Key('link.submit'),
            onPressed: _ready ? _submit : null,
            child: const Text('Envoyer la demande'),
          ),
        ],
      ),
    );
  }
}
