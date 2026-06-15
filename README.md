Gas Equipment Bot

AI-powered sales assistant and product intelligence platform for gas equipment distributors.

⸻

Overview

Gas Equipment Bot is an internal sales automation platform designed to help managers quickly find products, check stock availability, compare alternatives, answer technical questions and generate commercial proposals.

The bot combines:

* Real-time inventory data
* Supplier catalogs
* Internal knowledge base
* AI-powered product assistance

⸻

Business Problem

Sales managers often need to:

* Check stock availability
* Compare equipment
* Find alternatives
* Verify supplier pricing
* Explain technical differences
* Handle warranty and defect questions

Traditionally this required switching between:

* 1C
* Excel files
* Supplier catalogs
* Product manuals
* Internal documentation

Gas Equipment Bot consolidates these workflows into a single interface.

⸻

Main Capabilities

Product Search

Search across:

* 1C catalog
* Inventory balances
* Reserved stock
* Purchase prices
* Supplier catalogs

Supported categories:

* Boilers
* Water heaters
* Radiators
* Pumps
* Chimney systems
* Stabilizers

⸻

AI Sales Assistant

Supports:

* Product explanations
* Equipment comparison
* Alternative recommendations
* Technical consultations
* Sales positioning
* Customer-facing explanations

Example questions:

* Difference between Lemax Classic and Premium
* Alternative to Baxi Eco 4S 24F
* Which boiler fits a specific application
* Chimney compatibility questions

⸻

Knowledge Base System

Structured internal knowledge base covering:

* Boilers
* Water heaters
* Chimney systems
* Pumps
* Radiators
* Warranty procedures
* Supplier policies
* Defect handling workflows

⸻

Supplier Intelligence

Capabilities:

* Supplier price import
* Price comparison
* Best offer detection
* Supplier catalog search
* Stock-aware recommendations

⸻

Snapshot Fallback System

To ensure availability during PostgreSQL outages:

* Automatic catalog snapshots
* Scheduled snapshot refresh
* Last-known-good inventory data
* Graceful fallback mode

Managers can continue searching products even if the primary database is temporarily unavailable.

⸻

Architecture

1C PostgreSQL

Supplier Catalogs

Knowledge Base

↓

Business Services

↓

AI Layer

↓

Telegram Bot

↓

Sales Managers

⸻

Technology Stack

Core

* Python 3.12
* Aiogram 3
* PostgreSQL
* SQLAlchemy

Data

* Pandas
* Redis

AI

* Yandex AI Studio
* Qwen Models
* Retrieval Layer
* Internal Knowledge Base

Infrastructure

* Docker
* Systemd
* Linux VPS

⸻

Reliability

Implemented:

* PostgreSQL integration
* Redis caching
* Snapshot fallback catalog
* Automatic snapshot refresh
* Error recovery mechanisms

⸻

Current Status

Production / Internal Commercial Use

Implemented:

* Product search
* Inventory lookup
* Supplier catalog search
* AI sales assistant
* Knowledge base retrieval
* Alternative recommendations
* Snapshot fallback system

Used by real sales managers inside a gas equipment distribution company.

⸻

Long-Term Roadmap

Knowledge Base Expansion

Expand technical expertise across all product groups.

Passport Intelligence

Automatic extraction of technical specifications from product documentation.

Supplier Intelligence

Unified supplier comparison and purchasing intelligence.

Retrieval Layer V2

Advanced contextual search and ranking.

AI Sales Engineer

Full AI assistant capable of:

* Product recommendations
* Technical consultations
* Supplier analysis
* Commercial proposal support

⸻

Project Type

Commercial Internal Product

Built for real-world sales operations and integrated with production business data.
