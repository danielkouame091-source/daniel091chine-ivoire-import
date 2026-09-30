import 'package:freezed_annotation/freezed_annotation.dart';

part 'invoice.freezed.dart';
part 'invoice.g.dart';

@freezed
class Invoice with _$Invoice {
  const factory Invoice({
    required String id,
    required String numero,
    required String dateFacture,
    required String dateEcheance,
    required int totalHt,
    required int totalTva,
    required int totalTtc,
    required int montantEncaisse,
    required int soldeDu,
    required String statut,
    required int joursRetard,
    @Default(false) bool peutPayerEnLigne,
    String? fneReference,
    String? clientNom,
  }) = _Invoice;

  factory Invoice.fromJson(Map<String, dynamic> json) => _$InvoiceFromJson(json);
}
