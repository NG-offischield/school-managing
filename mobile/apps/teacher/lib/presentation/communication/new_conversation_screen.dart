import 'package:flutter/material.dart';
import 'package:provider/provider.dart';
import 'package:school_core/school_core.dart';

import '../../data/teacher_repository.dart';
import '../../models/models.dart';

/// New conversation: to the administration, or to a parent of one of my
/// pupils. The list comes from the server (GET /teacher/contacts/: only the
/// verified parents of the pupils I teach now, never the whole school); the
/// filter below only narrows that list. The server re-checks on send.
class NewConversationScreen extends StatefulWidget {
  const NewConversationScreen({super.key});

  @override
  State<NewConversationScreen> createState() => _NewConversationScreenState();
}

class _NewConversationScreenState extends State<NewConversationScreen> {
  final _title = TextEditingController();
  final _body = TextEditingController();
  final _filter = TextEditingController();
  bool _toParent = false;
  Future<List<PupilContacts>>? _contacts;
  PupilContacts? _pupil;
  ParentContact? _parent;
  bool _busy = false;
  String? _error;
  String? _clientId; // same intent = same client id: a resend creates no duplicate

  @override
  void dispose() {
    _title.dispose();
    _body.dispose();
    _filter.dispose();
    super.dispose();
  }

  void _chooseParent(bool value) {
    setState(() {
      _toParent = value;
      _clientId = null;
      if (value) _contacts ??= context.read<TeacherRepository>().contacts()..ignore();
    });
  }

  void _reload() => setState(() => _contacts = context.read<TeacherRepository>().contacts()..ignore());

  void _select(PupilContacts pupil, ParentContact parent) => setState(() {
    _pupil = pupil;
    _parent = parent;
    _clientId = null;
  });

  bool get _ready => !_busy && _body.text.trim().isNotEmpty && (!_toParent || _parent != null);

  Future<void> _send() async {
    if (!_ready) return;
    setState(() {
      _busy = true;
      _error = null;
    });
    _clientId ??= newClientId();
    try {
      final conversation = await context.read<TeacherRepository>().startConversation(
        type: _toParent ? 'PARENT_TEACHER' : 'ADMINISTRATION',
        participants: _toParent ? [_parent!.member] : const [],
        student: _toParent ? _pupil!.student : null,
        title: _title.text,
        body: _body.text.trim(),
        clientId: _clientId!,
      );
      if (mounted) Navigator.of(context).pop(conversation);
    } on ApiException catch (error) {
      if (mounted) setState(() => _error = error.userMessage);
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(title: Text(tr('Nouveau message'))),
      body: ListView(
        padding: const EdgeInsets.all(16),
        children: [
          if (_error != null) ...[MessageBanner(_error!), const SizedBox(height: 12)],
          SegmentedButton<bool>(
            segments: [
              ButtonSegment(value: false, label: Text(tr('Administration')), icon: Icon(Icons.apartment_outlined)),
              ButtonSegment(
                value: true,
                label: Text(tr('Parent d\'élève'), key: Key('compose.parent')),
                icon: Icon(Icons.family_restroom_outlined),
              ),
            ],
            selected: {_toParent},
            onSelectionChanged: (value) => _chooseParent(value.first),
          ),
          if (_toParent) ...[const SizedBox(height: 14), _contactsList()],
          const SizedBox(height: 14),
          TextField(
            key: const Key('message.title'),
            controller: _title,
            decoration: InputDecoration(labelText: tr('Objet (facultatif)')),
          ),
          const SizedBox(height: 12),
          TextField(
            key: const Key('message.body'),
            controller: _body,
            minLines: 4,
            maxLines: 8,
            onChanged: (_) => setState(() {}),
            decoration: InputDecoration(labelText: tr('Message'), alignLabelWithHint: true),
          ),
          const SizedBox(height: 18),
          FilledButton.icon(
            key: const Key('message.send'),
            onPressed: _ready ? _send : null,
            icon: const Icon(Icons.send),
            label: Text(tr('Envoyer')),
          ),
        ],
      ),
    );
  }

  Widget _contactsList() {
    return FutureBuilder<List<PupilContacts>>(
      future: _contacts,
      builder: (context, snapshot) {
        if (snapshot.connectionState != ConnectionState.done) return const LinearProgressIndicator();
        if (snapshot.hasError) {
          final error = snapshot.error;
          return Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              MessageBanner(error is ApiException ? error.userMessage : tr('Liste indisponible.')),
              TextButton(key: const Key('contacts.retry'), onPressed: _reload, child: Text(tr('Réessayer'))),
            ],
          );
        }
        final pupils = snapshot.data ?? const [];
        if (pupils.isEmpty) {
          return Text(
            tr('Aucun élève dans vos classes actuelles : aucun parent à contacter.'),
            key: Key('contacts.empty'),
          );
        }
        final query = _filter.text.trim().toLowerCase();
        final shown = query.isEmpty ? pupils : pupils.where((p) => p.name.toLowerCase().contains(query)).toList();
        return Column(
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: [
            Text(tr('Parents vérifiés des élèves de vos classes.'), style: TextStyle(color: Tokens.textSecondary)),
            const SizedBox(height: 8),
            TextField(
              key: const Key('contacts.filter'),
              controller: _filter,
              onChanged: (_) => setState(() {}),
              decoration: InputDecoration(prefixIcon: Icon(Icons.search), labelText: tr('Élève')),
            ),
            const SizedBox(height: 8),
            if (shown.isEmpty) Text(tr('Aucun élève ne correspond.')),
            for (final pupil in shown)
              Card(
                key: Key('pupil.${pupil.student}'),
                child: Padding(
                  padding: const EdgeInsets.symmetric(vertical: 6),
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Padding(
                        padding: const EdgeInsets.fromLTRB(16, 6, 16, 2),
                        child: Text(pupil.name, style: const TextStyle(fontWeight: FontWeight.w600)),
                      ),
                      if (pupil.parents.isEmpty)
                        Padding(
                          padding: EdgeInsets.fromLTRB(16, 2, 16, 8),
                          child: Text(tr('Aucun parent vérifié.'), style: TextStyle(color: Tokens.textSecondary)),
                        ),
                      for (final parent in pupil.parents)
                        ListTile(
                          key: Key('parent.${pupil.student}.${parent.member}'),
                          dense: true,
                          onTap: () => _select(pupil, parent),
                          leading: Icon(
                            _pupil?.student == pupil.student && _parent?.member == parent.member
                                ? Icons.radio_button_checked
                                : Icons.radio_button_unchecked,
                            color: Tokens.primary,
                          ),
                          title: Text(parent.name),
                          subtitle: Text(parent.relationshipLabel),
                        ),
                    ],
                  ),
                ),
              ),
          ],
        );
      },
    );
  }
}
