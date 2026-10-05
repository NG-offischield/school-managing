/// One payment of one invoice, from the confirmation to the server's answer.
///
/// Idempotency (ADR 0013 §5): the key is created ONCE per payment intent and
/// sent with every attempt of that intent.
/// - answer lost (network down, timeout, 5xx): the outcome is UNKNOWN, the
///   key is kept; « Réessayer » replays it and the server returns the payment
///   it already made (never a second debit);
/// - definitive answer (success, refusal, insufficient funds..., 4xx): the
///   intent is over; a new attempt is a new intent with a new key.
/// While an intent is unresolved, its wallet cannot change (same key + other
/// request = 409 idempotency_conflict).
/// One submission at a time: a second tap while paying does nothing.
library;

import 'dart:math';

import 'package:flutter/foundation.dart';
import 'package:school_core/school_core.dart';

import '../models/models.dart';
import 'parent_repository.dart';

final _random = Random.secure();

/// Opaque, unguessable, unique per intent.
String newIdempotencyKey() =>
    'mob-${List.generate(16, (_) => _random.nextInt(256).toRadixString(16).padLeft(2, '0')).join()}';

class PaymentIntent {
  PaymentIntent({required this.childId, required this.invoice, required this.wallet, String? key})
    : key = key ?? newIdempotencyKey();

  final String childId;
  final Invoice invoice;
  final Wallet wallet;
  final String key;
}

enum PayState { ready, paying, done, unknown, refused }

class PaymentFlow extends ChangeNotifier {
  PaymentFlow(this.repository, {required this.childId, required this.invoice});

  final ParentRepository repository;
  final String childId;
  final Invoice invoice;

  PayState state = PayState.ready;
  Wallet? wallet;

  /// Answer of the server (success or recorded failure).
  Payment? payment;

  /// Refusal before any payment (403 / 404 / 409 / 400), or the lost answer.
  ApiException? error;

  PaymentIntent? _intent;

  /// The intent waiting for an answer (key kept for the retry).
  PaymentIntent? get pending => _intent;

  bool get walletLocked => _intent != null;

  void chooseWallet(Wallet value) {
    if (walletLocked || state == PayState.paying) return;
    wallet = value;
    notifyListeners();
  }

  Future<void> pay() async {
    final chosen = wallet;
    if (state == PayState.paying || chosen == null) return; // double tap / nothing chosen
    final intent = _intent ??= PaymentIntent(childId: childId, invoice: invoice, wallet: chosen);
    state = PayState.paying;
    error = null;
    notifyListeners();
    try {
      payment = await repository.pay(intent);
      state = PayState.done;
      _intent = null; // definitive: a later attempt is a new intent
    } on NetworkException catch (e) {
      error = e;
      state = PayState.unknown; // keep the key: the retry replays it
    } on ServerException catch (e) {
      error = e;
      state = PayState.unknown;
    } on ApiException catch (e) {
      error = e;
      state = PayState.refused;
      _intent = null;
    }
    notifyListeners();
  }

  /// After a recorded failure (declined, insufficient funds...): try again,
  /// as a NEW payment (new key), possibly with another wallet.
  void startOver() {
    if (state == PayState.paying || _intent != null) return;
    payment = null;
    error = null;
    state = PayState.ready;
    notifyListeners();
  }
}
