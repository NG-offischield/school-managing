import 'package:flutter/material.dart';
import 'package:provider/provider.dart';
import 'package:school_core/school_core.dart';

import '../../data/parent_repository.dart';
import '../../models/models.dart';
import '../common.dart';

/// New conversation: to the administration, or to a teacher of my child
/// (the list comes from the server: only the teachers of a VERIFIED child's
/// current courses). The server re-checks who may write to whom.
class NewConversationScreen extends StatefulWidget {
  const NewConversationScreen({super.key});

  @override
  State<NewConversationScreen> createState() => _NewConversationScreenState();
}

class _NewConversationScreenState extends State<NewConversationScreen> {
  final _title = TextEditingController();
  final _body = TextEditingController();
  bool _toTeacher = false;
  Future<List<TeacherContact>>? _teachers;
  TeacherContact? _teacher;
  bool _busy = false;
  String? _error;
  String? _clientId; // same intent = same client id: a resend creates no duplicate

  @override
  void dispose() {
    _title.dispose();
    _body.dispose();
    super.dispose();
  }

  Child? get _child => context.read<ChildScope>().selected;

  void _chooseTeacher(bool value) {
    setState(() {
      _toTeacher = value;
      _teacher = null;
      final child = _child;
      if (value && child != null) _teachers = context.read<ParentRepository>().teachers(child.id)..ignore();
    });
  }

  bool get _ready => !_busy && _body.text.trim().isNotEmpty && (!_toTeacher || _teacher != null);

  Future<void> _send() async {
    if (!_ready) return;
    setState(() {
      _busy = true;
      _error = null;
    });
    final repo = context.read<ParentRepository>();
    _clientId ??= newClientId();
    try {
      final conversation = await repo.startConversation(
        type: _toTeacher ? 'PARENT_TEACHER' : 'ADMINISTRATION',
        participants: _toTeacher ? [_teacher!.member] : const [],
        student: _toTeacher ? _child?.id : null,
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
    final child = context.watch<ChildScope>().selected;
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
                enabled: child != null,
                label: Text(tr('Enseignant')),
                icon: const Icon(Icons.school_outlined),
              ),
            ],
            selected: {_toTeacher},
            onSelectionChanged: (value) => _chooseTeacher(value.first),
          ),
          if (_toTeacher && child != null) ...[
            const SizedBox(height: 14),
            Text(tr('Au sujet de {0}', [child.name]), style: TextStyle(color: Tokens.textSecondary)),
            const SizedBox(height: 8),
            FutureBuilder<List<TeacherContact>>(
              future: _teachers,
              builder: (context, snapshot) {
                if (snapshot.connectionState != ConnectionState.done) return const LinearProgressIndicator();
                if (snapshot.hasError) {
                  final error = snapshot.error;
                  return MessageBanner(error is ApiException ? error.userMessage : tr('Liste indisponible.'));
                }
                final teachers = snapshot.data ?? const [];
                if (teachers.isEmpty) return Text(tr('Aucun enseignant pour cette classe.'));
                return Column(
                  children: [
                    for (final t in teachers)
                      Card(
                        child: ListTile(
                          key: Key('teacher.${t.member}'),
                          onTap: () => setState(() => _teacher = t),
                          leading: Icon(
                            _teacher?.member == t.member ? Icons.radio_button_checked : Icons.radio_button_unchecked,
                            color: Tokens.primary,
                          ),
                          title: Text(t.name),
                          subtitle: Text(t.subjects.join(', ')),
                        ),
                      ),
                  ],
                );
              },
            ),
          ],
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
}
