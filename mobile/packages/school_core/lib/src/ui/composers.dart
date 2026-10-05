import 'package:flutter/material.dart';
import 'package:provider/provider.dart';

import '../api/api_error.dart';
import '../data/communication.dart';
import '../widgets/widgets.dart';

/// Message to the administration (every role may write to it; the server
/// decides who receives it). Same client id on a resend: no duplicate.
class AdminMessageScreen extends StatefulWidget {
  const AdminMessageScreen({super.key});

  @override
  State<AdminMessageScreen> createState() => _AdminMessageScreenState();
}

class _AdminMessageScreenState extends State<AdminMessageScreen> {
  final _title = TextEditingController();
  final _body = TextEditingController();
  bool _busy = false;
  String? _error;
  String? _clientId;

  @override
  void dispose() {
    _title.dispose();
    _body.dispose();
    super.dispose();
  }

  bool get _ready => !_busy && _body.text.trim().isNotEmpty;

  Future<void> _send() async {
    if (!_ready) return;
    setState(() {
      _busy = true;
      _error = null;
    });
    _clientId ??= newClientId();
    try {
      final conversation = await context.read<CommunicationRepository>().startConversation(
        type: 'ADMINISTRATION',
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
      appBar: AppBar(title: const Text('Message à l\'administration')),
      body: ListView(
        padding: const EdgeInsets.all(16),
        children: [
          if (_error != null) ...[MessageBanner(_error!), const SizedBox(height: 12)],
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

/// New complaint, submitted at once; optionally about a pupil the caller
/// may see (the server checks it).
class ComplaintComposer extends StatefulWidget {
  const ComplaintComposer({super.key, this.studentId, this.studentLabel});

  final String? studentId;
  final String? studentLabel;

  @override
  State<ComplaintComposer> createState() => _ComplaintComposerState();
}

class _ComplaintComposerState extends State<ComplaintComposer> {
  final _subject = TextEditingController();
  final _description = TextEditingController();
  String _category = 'OTHER';
  bool _aboutStudent = true;
  bool _busy = false;
  String? _error;

  @override
  void dispose() {
    _subject.dispose();
    _description.dispose();
    super.dispose();
  }

  bool get _ready => !_busy && _subject.text.trim().isNotEmpty && _description.text.trim().isNotEmpty;

  Future<void> _submit() async {
    if (!_ready) return;
    setState(() {
      _busy = true;
      _error = null;
    });
    try {
      final complaint = await context.read<CommunicationRepository>().fileComplaint(
        category: _category,
        subject: _subject.text,
        description: _description.text,
        student: _aboutStudent ? widget.studentId : null,
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
          if (widget.studentId != null)
            SwitchListTile(
              contentPadding: EdgeInsets.zero,
              value: _aboutStudent,
              onChanged: (value) => setState(() => _aboutStudent = value),
              title: Text('Concerne ${widget.studentLabel ?? 'l\'élève'}'),
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
            onPressed: _ready ? _submit : null,
            child: const Text('Transmettre'),
          ),
        ],
      ),
    );
  }
}
