import 'package:flutter/material.dart';
import 'package:provider/provider.dart';
import 'package:school_core/school_core.dart';

import '../../data/parent_repository.dart';
import '../../data/pdf_store.dart';
import '../../models/models.dart';

/// Downloads the OFFICIAL receipt (built by the server with the school's
/// identity and branding — never the software's), keeps it in the app's
/// private folder and opens it when the phone has a PDF viewer.
Future<void> downloadReceipt(BuildContext context, Payment payment) async {
  final repo = context.read<ParentRepository>();
  final store = context.read<PdfStore>();
  final messenger = ScaffoldMessenger.of(context);
  void say(String text) => messenger.showSnackBar(SnackBar(content: Text(text)));
  try {
    final bytes = await repo.receiptPdf(payment.id);
    final path = await store.save('recu-${payment.reference}.pdf', bytes);
    final opened = await store.open(path);
    say(
      opened
          ? 'Reçu ${payment.reference} ouvert.'
          : 'Reçu ${payment.reference} enregistré dans l\'application (aucune application PDF pour l\'ouvrir).',
    );
  } on ApiException catch (error) {
    say(error.userMessage);
  }
}
