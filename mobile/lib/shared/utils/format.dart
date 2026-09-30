import 'package:intl/intl.dart';

class Format {
  static final _xof = NumberFormat.decimalPattern('fr_FR');

  static String xof(int? montant) {
    if (montant == null) return '—';
    return '${_xof.format(montant)} FCFA';
  }

  static String xofCompact(num montant) {
    if (montant >= 1_000_000_000) return '${(montant / 1_000_000_000).toStringAsFixed(1)} Md';
    if (montant >= 1_000_000)     return '${(montant / 1_000_000).toStringAsFixed(1)} M';
    if (montant >= 1_000)         return '${(montant / 1_000).toStringAsFixed(0)} K';
    return montant.toString();
  }

  static String date(String? iso) {
    if (iso == null) return '—';
    try {
      return DateFormat('dd/MM/yyyy').format(DateTime.parse(iso));
    } catch (_) {
      return iso;
    }
  }

  static String dateTime(String? iso) {
    if (iso == null) return '—';
    try {
      return DateFormat('dd/MM/yyyy HH:mm').format(DateTime.parse(iso));
    } catch (_) {
      return iso;
    }
  }
}
