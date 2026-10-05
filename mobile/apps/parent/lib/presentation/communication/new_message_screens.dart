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
      appBar: AppBar(title: const Text('Nouveau message')),
      body: ListView(
        padding: const EdgeInsets.all(16),
        children: [
          if (_error != null) ...[MessageBanner(_error!), const SizedBox(height: 12)],
          SegmentedButton<bool>(
            segments: [
              const ButtonSegment(value: false, label: Text('Administration'), icon: Icon(Icons.apartment_outlined)),
              ButtonSegment(
                value: true,
                enabled: child != null,
                label: const Text('Enseignant'),
                icon: const Icon(Icons.school_outlined),
              ),
            ],
            selected: {_toTeacher},
            onSelectionChanged: (value) => _chooseTeacher(value.first),
          ),
          if (_toTeacher && child != null) ...[
            const SizedBox(height: 14),
            Text('Au sujet de ${child.name}', style: const TextStyle(color: Tokens.textSecondary)),
            const SizedBox(height: 8),
            FutureBuilder<List<TeacherContact>>(
              future: _teachers,
              builder: (context, snapshot) {
                if (snapshot.connectionState != ConnectionState.done) return const LinearProgressIndicator();
                if (snapshot.hasError) {
                  final error = snapshot.error;
                  return MessageBanner(error is ApiException ? error.userMessage : 'Liste indisponible.');
                }
                final teachers = snapshot.data ?? const [];
                if (teachers.isEmpty) return const Text('Aucun enseignant pour cette classe.');
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
            decoration: const InputDecoration(labelText: 'Objet (facultatif)'),
          ),
          const SizedBox(height: 12),
          TextField(
            key: const Key('message.body'),
            controller: _body,
            minLines: 4,
            maxLines: 8,
            onChanged: (_) => setState(() {}),
            decoration: const InputDecoration(labelText: 'Message', alignLabelWithHint: true),
          ),
          const SizedBox(height: 18),
          FilledButton.icon(
            key: const Key('message.send'),
            onPressed: _ready ? _send : null,
            icon: const Icon(Icons.send),
            label: const Text('Envoyer'),
          ),
        ],
      ),
    );
  }
}

/// New complaint (submitted at once), optionally about the selected child.
class NewComplaintScreen extends StatefulWidget {
  const NewComplaintScreen({super.key});

  @override
  State<NewComplaintScreen> createState() => _NewComplaintScreenState();
}

class _NewComplaintScreenState extends State<NewComplaintScreen> {
  final _subject = TextEditingController();
  final _description = TextEditingController();
  String _category = 'OTHER';
  bool _aboutChild = true;
  bool _busy = false;
  String? _error;

  @override
  void dispose() {
    _subject.dispose();
    _description.dispose();
    super.dispose();
  }

  bool get _ready => !_busy && _subject.text.trim().isNotEmpty && _description.text.trim().isNotEmpty;

  Future<void> _submit(Child? child) async {
    if (!_ready) return;
    setState(() {
      _busy = true;
      _error = null;
    });
    try {
      final complaint = await context.read<ParentRepository>().fileComplaint(
        category: _category,
        subject: _subject.text,
        description: _description.text,
        student: _aboutChild ? child?.id : null,
      );
      if (mounted) Navigator.of(context).pop(complaint);
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
      appBar: AppBar(title: const Text('Nouvelle réclamation')),
      body: ListView(
        padding: const EdgeInsets.all(16),
        children: [
          if (_error != null) ...[MessageBanner(_error!), const SizedBox(height: 12)],
          DropdownButtonFormField<String>(
            isExpanded: true,
            initialValue: _category,
            decoration: const InputDecoration(labelText: 'Catégorie'),
            items: [
              for (final entry in complaintCategories.entries)
                DropdownMenuItem(value: entry.key, child: Text(entry.value)),
            ],
            onChanged: (value) => setState(() => _category = value ?? 'OTHER'),
          ),
          if (child != null)
            SwitchListTile(
              contentPadding: EdgeInsets.zero,
              value: _aboutChild,
              onChanged: (value) => setState(() => _aboutChild = value),
              title: Text('Concerne ${child.name}'),
            ),
          const SizedBox(height: 8),
          TextField(
            key: const Key('complaint.subject'),
            controller: _subject,
            onChanged: (_) => setState(() {}),
            decoration: const InputDecoration(labelText: 'Objet'),
          ),
          const SizedBox(height: 12),
          TextField(
            key: const Key('complaint.description'),
            controller: _description,
            minLines: 4,
            maxLines: 8,
            onChanged: (_) => setState(() {}),
            decoration: const InputDecoration(labelText: 'Description', alignLabelWithHint: true),
          ),
          const SizedBox(height: 18),
          FilledButton(
            key: const Key('complaint.submit'),
            onPressed: _ready ? () => _submit(child) : null,
            child: const Text('Transmettre'),
          ),
        ],
      ),
    );
  }
}
