# Batch-Aware Inventory Engine for Perishable Goods

**Course:** MSCS-532-M70 – Algorithms and Data Structures  
**University:** University of the Cumberlands  
**Semester:** Fall 2026

## Project Overview
This project proposes a Python-based inventory management system for perishable grocery products. It tracks individual product batches, expiration dates, stock availability, and reservations using efficient data structures.

## Data Structures
- **Hash Table (Dictionary):** Provides O(1) average-time batch lookup by ID.
- **Per-SKU Min-Heap:** Supports First-Expire, First-Out (FEFO) inventory selection.
- **Global Min-Heap:** Tracks the next expiring batch across all products.

## Key Operations
- Receive and track inventory batches
- Check available stock
- Reserve and fulfill customer orders
- Release canceled reservations
- Identify and remove expired batches

## Design Approach
The system prioritizes efficient inventory lookups and expiration handling. It uses version numbers to identify stale heap entries and maintains batch-level inventory accuracy.

## Project Status
**Phase 1 – Design and Data Structure Selection**

The repository contains the Phase 1 design brief and initial implementation materials. The complete inventory engine is planned for subsequent development.

## Technologies
- Python 3
- Hash Tables
- Min-Heaps / Priority Queues
- Algorithm Complexity Analysis
