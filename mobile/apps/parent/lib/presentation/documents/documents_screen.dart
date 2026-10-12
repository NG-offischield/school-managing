import 'package:flutter/material.dart';
import 'package:provider/provider.dart';
import 'package:school_core/school_core.dart';

import '../../data/parent_repository.dart';
import '../../data/pdf_store.dart';
import '../../models/models.dart';
import '../common.dart';

/// Bulletins et documents of the selected child: the OFFICIAL report cards
/// (the server never gives a parent a provisional one), their PDF — built
/// by the server with the SCHOOL's branding — and the authenticity check of
/// a printed document. Receipts are on the payments screen.
class DocumentsScreen extends StatelessWidget {
  const DocumentsScreen({super.key});

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(
        title: Text(tr('Bulletins et documents')),
        actions: [
          IconButton(
            key: const Key('documents.verify'),
            tooltip: tr('Vérifier un document imprimé'),
            icon: const Icon(Icons.verified_outlined),
            onPressed: () => _verify(context),
          ),
          const ChildSwitcher(),
        ],
      ),
      body: ChildBody(
        builder: (context, child) => _ReportCards(key: ValueKey(child.id), child: child),
      ),
    );
  }

  Future<void> _verify(BuildContext context) async {
    final repo = context.read<ParentRepository>();
    final code = await showDialog<String>(context: context, builder: (_) => const _CodeDialog());
    if (code == null || code.trim().isEmpty || !context.mounted) return;
    try {
      final check = await repo.verifyDocument(code);
      if (!context.mounted) return;
      showMessage(
        context,
        check.current
            ? tr('Document authentique{0}.', [check.title == null ? '' : ' : ${check.title}'])
            : tr('Document authentique mais remplacé par une version plus récente.'),
      );
    } on NotFoundException {
      if (context.mounted) {
        showMessage(context, tr('Code inconnu : ce document n\'a pas été émis par l\'établissement.'));
      }
    } on ApiException catch (error) {
      if (context.mounted) showMessage(context, error.userMessage);
    }
  }
}

class _CodeDialog extends StatefulWidget {
  const _CodeDialog();

  @override
  State<_CodeDialog> createState() => _CodeDialogState();
}

class _CodeDialogState extends State<_CodeDialog> {
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
      title: Text(tr('Vérifier un document')),
      content: TextField(
        key: const Key('verify.code'),
        controller: _code,
        autofocus: true,
        textCapitalization: TextCapitalization.characters,
        decoration: InputDecoration(
          labelText: tr('Code de vérification'),
          helperText: tr('Imprimé en bas du document.'),
        ),
      ),
      actions: [
        TextButton(onPressed: () => Navigator.of(context).pop(), child: Text(tr('Annuler'))),
        FilledButton(onPressed: () => Navigator.of(context).pop(_code.text), child: Text(tr('Vérifier'))),
      ],
    );
  }
}

class _ReportCards extends StatefulWidget {
  const _ReportCards({super.key, required this.child});

  final Child child;

  @override
  State<_ReportCards> createState() => _ReportCardsState();
}

class _ReportCardsState extends State<_ReportCards> {
  Future<List<ReportCard>>? _future;
  String? _downloading;

  @override
  void initState() {
    super.initState();
    _load();
  }

  void _load() => setState(() {
    _future = context.read<ParentRepository>().reportCards(widget.child.id)..ignore();
  });

  Future<void> _download(ReportCard card) async {
    final repo = context.read<ParentRepository>();
    final store = context.read<PdfStore>();
    setState(() => _downloading = card.id);
    try {
      final bytes = await repo.reportCardPdf(card.id);
      await store.save('bulletin-${widget.child.studentNumber}-${card.period}.pdf', bytes);
      if (mounted) showMessage(context, tr('Bulletin « {0} » enregistré dans l\'application.', [card.period]));
    } on ApiException catch (error) {
      if (mounted) showMessage(context, error.userMessage);
    } finally {
      if (mounted) setState(() => _downloading = null);
    }
  }

  @override
  Widget build(BuildContext context) {
    return AsyncBody<List<ReportCard>>(
      future: _future,
      onRetry: _load,
      isEmpty: (rows) => rows.isEmpty,
      emptyText: tr('Aucun bulletin validé pour le moment.'),
      builder: (context, cards) => ListView(
        padding: const EdgeInsets.fromLTRB(16, 8, 16, 24),
        children: [
          Text(widget.child.name, style: const TextStyle(fontSize: 18, fontWeight: FontWeight.w700)),
          SectionTitle(tr('Bulletins officiels')),
          for (final card in cards)
            Card(
              child: ExpansionTile(
                key: Key('card.${card.id}'),
                title: Text(card.period, style: const TextStyle(fontWeight: FontWeight.w700)),
                subtitle: Text(
                  [
                    if (card.average != null)
                      tr('Moyenne {0}{1}', [card.average, card.scaleMax == null ? '' : ' / ${card.scaleMax}']),
                    if (card.rank != null)
                      tr('Rang {0}{1}', [card.rank, card.classSize == null ? '' : ' / ${card.classSize}']),
                  ].join(' · '),
                ),
                childrenPadding: const EdgeInsets.fromLTRB(16, 0, 16, 12),
                children: [
                  for (final line in card.lines)
                    InfoRow(tr('{0} (coef. {1})', [line.subject, line.coefficient]), line.average ?? '—'),
                  const SizedBox(height: 8),
                  Align(
                    alignment: Alignment.centerRight,
                    child: FilledButton.icon(
                      key: Key('card.pdf.${card.id}'),
                      onPressed: _downloading == null ? () => _download(card) : null,
                      icon: _downloading == card.id
                          ? const SizedBox(width: 16, height: 16, child: CircularProgressIndicator(strokeWidth: 2))
                          : const Icon(Icons.picture_as_pdf_outlined),
                      label: Text(tr('Télécharger le PDF')),
                    ),
                  ),
                ],
              ),
            ),
        ],
      ),
    );
  }
}
