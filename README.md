# Batch-Aware Inventory Engine for Perishable Goods

## Project Overview

The Batch-Aware Inventory Engine is a Python implementation for managing perishable inventory at the delivery-batch level. Instead of tracking only a total quantity for each product, the engine stores each batch separately with its own expiration date, sell-by date, physical quantity, and reservation information.

Reservations follow the **First-Expire, First-Out (FEFO)** policy. Stock with the earliest expiration date is allocated first. A configurable sell-by buffer prevents inventory from remaining available too close to its printed expiration date.

This project is an in-memory academic prototype. It is designed to demonstrate data structures, algorithm selection, inventory consistency, and complexity trade-offs. It is not a production inventory service or a REST API.

## Main Features

- Insert, search, and delete inventory batches.
- Track inventory separately by SKU and batch.
- Calculate sell-by dates using a configurable expiration buffer (three days by default).
- Query sellable stock by SKU.
- Reserve inventory using FEFO allocation.
- Enforce all-or-nothing reservations.
- Fulfill or cancel existing reservations.
- Process expired batches and generate reconciliation reports for affected orders.
- Reject invalid input and operations that would violate inventory rules.
- Use versioned lazy invalidation to handle outdated heap entries.

## Project Structure

```text
.
├── batch.py             # Batch data model and quantity validation
├── heap_manager.py      # FEFO and expiration priority queues
├── inventory.py         # Inventory state and batch lifecycle operations
├── reservations.py      # Reservation, fulfillment, and cancellation
├── demo.py              # Demonstration workflow
├── tests/
│   ├── helpers.py
│   ├── test_batches.py
│   ├── test_expiration.py
│   └── test_reservations.py
└── documentation/
    ├── Technical_Design_Documentation_APA.docx
    └── Python_API_Reference_APA.docx
```

## Requirements

- Python 3.10 or later (the source uses modern type-hint syntax such as `X | None` and built-in generic types).
- No third-party runtime packages are required for the inventory engine or its unit tests. The implementation uses the Python standard library.

## Getting Started

1. Extract the project ZIP file.
2. Open a terminal or command prompt.
3. Change to the project directory:

   ```bash
   cd Batch_Aware_Inventory_Engine_Project
   ```

4. Run the demonstration:

   ```bash
   python demo.py
   ```

## Running the Tests

Run the complete standard-library test suite from the project root:

```bash
python -m unittest discover tests -v
```

The test suite covers batch insertion and deletion, validation, FEFO allocation, reservation and fulfillment behavior, cancellation, expiration processing, reconciliation reports, multiple SKUs, and stale heap entries.

At the time this project package was prepared, all **42 tests passed** using the command above.

## Basic Usage

The following example adds two milk batches, checks availability, reserves stock, and fulfills the order.

```python
from datetime import date

from inventory import Inventory
from reservations import reserve, fulfill, cancel_reservation

today = date(2026, 11, 1)

inventory = Inventory(expiry_buffer_days=3)

inventory.insert_batch(
    batch_id="B101",
    sku="milk",
    quantity=20,
    expiry=date(2026, 11, 7),
    today=today,
)

inventory.insert_batch(
    batch_id="B102",
    sku="milk",
    quantity=30,
    expiry=date(2026, 11, 15),
    today=today,
)

print(inventory.available("milk", today))  # 50

allocation = reserve(
    inventory,
    order_id="ORD-1",
    sku="milk",
    qty=10,
    today=today,
)
print(allocation)  # Expected: {'B101': 10}

fulfilled = fulfill(inventory, "ORD-1", today)
print(fulfilled)
```

`cancel_reservation` is available when an order should be released instead of fulfilled:

```python
allocation = reserve(inventory, "ORD-2", "milk", 5, today)
cancelled = cancel_reservation(inventory, "ORD-2")
```

## Core Design

### Data Structures

- **Dictionaries (hash tables):** Provide average constant-time access to batches, orders, and per-SKU availability counters.
- **Per-SKU min-heaps:** Order batches by printed expiration date and support FEFO reservation.
- **Store-wide min-heap:** Orders expiration events by calculated sell-by date so due batches can be processed without scanning every SKU.
- **Version tokens:** Identify stale heap entries after a batch is invalidated or its state changes.
- **Order and batch hold ledgers:** Track which batches supply each order and which orders hold units from each batch.

### Reservation Policy

A reservation is planned against the earliest-expiring eligible batches. The engine checks whether the full requested quantity is available before committing reservation changes. If the requested quantity cannot be satisfied, it raises `ValueError` and does not create a partial reservation.

### Expiration Policy

The default sell-by date is:

```text
sell_by = expiry - expiry_buffer
```

A batch becomes unsellable when the supplied business date is greater than or equal to its sell-by date. Operations that query or modify dated inventory process due expiration events first.

## Important Rules and Behavior

- Batch IDs must be unique among active batches.
- Quantities must be positive whole numbers; Boolean values are rejected.
- Orders must have unique IDs and request a positive whole-number quantity.
- A batch cannot be deleted while it has reserved units.
- An order holding expired stock cannot be fulfilled.
- Cancelling a reservation returns units to availability only if the batch has not expired.
- The caller supplies the `today` date to date-sensitive operations.
- The system stores state in memory only; state is not saved when the process exits.

## Documentation

Two separate developer documents are included in the `documentation/` folder:

1. **Technical Design Documentation (APA):** Explains system architecture, functionality, algorithm and data-structure choices, complexity, testing, limitations, and design rationale.
2. **Python API Reference (APA):** Documents classes, methods, function signatures, parameters, return types, exceptions, side effects, and usage examples.

These documents are separate from this README.

## Current Limitations

- No database or file-based persistence.
- No concurrency control or thread safety.
- No REST endpoints, web interface, or authentication layer.
- Orders support one SKU and whole-order reservation/fulfillment only.
- Partial fulfillment and automatic re-reservation are not implemented.
- CSV bulk import is not implemented.
- Stale heap entries are cleaned up lazily and may temporarily increase heap size.
- `search_batch` returns a mutable `Batch` object; external mutation can bypass inventory consistency checks.

