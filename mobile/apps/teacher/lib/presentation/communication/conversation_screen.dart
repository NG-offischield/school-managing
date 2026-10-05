import 'dart:async';

import 'package:flutter/material.dart';
import 'package:provider/provider.dart';
import 'package:school_core/school_core.dart';

import '../../data/teacher_repository.dart';
import '../common.dart';
import '../home/home_shell.dart';

/// One conversation: history, live messages (WebSocket subscribe + resync),
/// send with a client_id kept across a network failure (no duplicate).
class ConversationScreen extends StatefulWidget {
  const ConversationScreen({super.key, required this.conversation});

  final Conversation conversation;

  @override
  State<ConversationScreen> createState() => _ConversationScreenState();
}

class _ConversationScreenState extends State<ConversationScreen> {
  final _text = TextEditingController();
  final _scroll = ScrollController();
  Future<List<ChatMessage>>? _future;
  List<ChatMessage> _messages = [];
  StreamSubscription<Map<String, dynamic>>? _live;
  String? _pendingClientId;
  String? _pendingBody;
  String? _error;
  bool _sending = false;
  late final LiveState _liveState; // kept: no context lookup in dispose()

  String get _myName => context.read<AuthService>().identity?.fullName ?? '';

  @override
  void initState() {
    super.initState();
    _load();
    final live = _liveState = context.read<LiveState>();
    live.client?.watch(widget.conversation.id);
    _live = live.messages.stream.listen((data) {
      final message = ChatMessage.fromJson(data, myName: _myName);
      if (message.conversation == widget.conversation.id && _messages.every((m) => m.id != message.id)) {
        setState(() => _messages = [..._messages, message]);
        _toBottom();
      }
    });
  }

  @override
  void dispose() {
    _live?.cancel();
    _liveState.client?.unwatch(widget.conversation.id);
    _text.dispose();
    _scroll.dispose();
    super.dispose();
  }

  void _load() {
    final repo = context.read<TeacherRepository>();
    setState(() {
      _future = repo.messages(widget.conversation.id, myName: _myName).then((rows) {
        _messages = rows;
        repo.markConversationRead(widget.conversation.id).catchError((_) {});
        _toBottom();
        return rows;
      })..ignore();
    });
  }

  void _toBottom() => WidgetsBinding.instance.addPostFrameCallback((_) {
    if (_scroll.hasClients) _scroll.jumpTo(_scroll.position.maxScrollExtent);
  });

  Future<void> _send() async {
    final body = _text.text.trim();
    if (body.isEmpty || _sending) return;
    final clientId = body == _pendingBody && _pendingClientId != null ? _pendingClientId! : newClientId();
    setState(() {
      _sending = true;
      _error = null;
    });
    try {
      final sent = await context.read<TeacherRepository>().send(
        widget.conversation.id,
        body,
        clientId: clientId,
        myName: _myName,
      );
      _pendingBody = _pendingClientId = null;
      _text.clear();
      if (_messages.every((m) => m.id != sent.id)) _messages = [..._messages, sent];
      _toBottom();
    } on NetworkException catch (error) {
      _pendingBody = body; // a retry reuses the same client_id
      _pendingClientId = clientId;
      _error = '${error.userMessage} Le message sera renvoyé sans doublon.';
    } on ApiException catch (error) {
      _error = error.userMessage;
    } finally {
      if (mounted) setState(() => _sending = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(title: Text(widget.conversation.label)),
      body: SafeArea(
        child: Column(
          children: [
            Expanded(
              child: AsyncBody<List<ChatMessage>>(
                future: _future,
                onRetry: _load,
                isEmpty: (_) => _messages.isEmpty,
                emptyText: 'Aucun message.',
                builder: (context, _) => ListView.builder(
                  controller: _scroll,
                  padding: const EdgeInsets.all(12),
                  itemCount: _messages.length,
                  itemBuilder: (context, index) => _Bubble(message: _messages[index]),
                ),
              ),
            ),
            if (_error != null)
              Padding(
                padding: const EdgeInsets.fromLTRB(12, 0, 12, 6),
                child: MessageBanner(_error!, tone: Tone.warning),
              ),
            Padding(
              padding: const EdgeInsets.fromLTRB(12, 4, 8, 10),
              child: Row(
                children: [
                  Expanded(
                    child: TextField(
                      key: const Key('conversation.input'),
                      controller: _text,
                      minLines: 1,
                      maxLines: 4,
                      textCapitalization: TextCapitalization.sentences,
                      decoration: const InputDecoration(hintText: 'Votre message'),
                      onChanged: (_) => setState(() {}),
                    ),
                  ),
                  const SizedBox(width: 6),
                  IconButton.filled(
                    key: const Key('conversation.send'),
                    tooltip: 'Envoyer',
                    onPressed: _text.text.trim().isEmpty || _sending ? null : _send,
                    icon: const Icon(Icons.send),
                  ),
                ],
              ),
            ),
          ],
        ),
      ),
    );
  }
}

class _Bubble extends StatelessWidget {
  const _Bubble({required this.message});

  final ChatMessage message;

  @override
  Widget build(BuildContext context) {
    final mine = message.mine;
    return Align(
      alignment: mine ? Alignment.centerRight : Alignment.centerLeft,
      child: Container(
        margin: const EdgeInsets.symmetric(vertical: 4),
        constraints: BoxConstraints(maxWidth: MediaQuery.sizeOf(context).width * 0.8),
        padding: const EdgeInsets.all(12),
        decoration: BoxDecoration(
          color: mine ? Tokens.primary : Tokens.surface,
          borderRadius: BorderRadius.circular(12),
          border: mine ? null : Border.all(color: Tokens.border),
        ),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            if (!mine)
              Text(
                message.sender,
                style: const TextStyle(fontWeight: FontWeight.w700, color: Tokens.navy, fontSize: 13),
              ),
            Text(
              message.body ?? '[Message masqué]',
              style: TextStyle(
                color: mine ? Colors.white : Tokens.text,
                fontStyle: message.body == null ? FontStyle.italic : null,
              ),
            ),
            for (final name in message.attachments)
              Text('📎 $name', style: TextStyle(color: mine ? Colors.white70 : Tokens.textSecondary, fontSize: 13)),
            if (message.at != null)
              Text(
                hm.format(message.at!),
                style: TextStyle(color: mine ? Colors.white70 : Tokens.textSecondary, fontSize: 11.5),
              ),
          ],
        ),
      ),
    );
  }
}
