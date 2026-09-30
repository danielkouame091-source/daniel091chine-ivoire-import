import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../../core/network/api_client.dart';
import '../data/invoices_repository.dart';
import '../data/models/invoice.dart';

enum InvoiceFilter { all, unpaid, overdue, paid }

final invoicesRepositoryProvider = Provider<InvoicesRepository>(
  (ref) => InvoicesRepository(ApiClient.dio),
);

final invoicesFilterProvider = StateProvider<InvoiceFilter>((ref) => InvoiceFilter.all);

final invoicesListProvider = FutureProvider.autoDispose<List<Invoice>>((ref) async {
  final repo = ref.watch(invoicesRepositoryProvider);
  return repo.list();
});

final invoiceDetailProvider = FutureProvider.autoDispose.family<Invoice, String>(
  (ref, id) async {
    final repo = ref.watch(invoicesRepositoryProvider);
    return repo.detail(id);
  },
);
