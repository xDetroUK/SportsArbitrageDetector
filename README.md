EDUCATIONAL PURPOSES ONLY!!!
Live Odds Comparator - Betting Arbitrage Tool
Overview
This application provides real-time comparison of live betting odds across multiple bookmakers (WinBet, Efbet, Betano) and betting exchanges (OrbitX). The tool identifies arbitrage opportunities by analyzing price discrepancies between back and lay odds.

Key Features
Core Functionality
Multi-Source Odds Comparison: Simultaneously monitors 3 bookmakers and 1 betting exchange

Arbitrage Detection: Automatically identifies profitable arbitrage opportunities

Real-time Updates: Refreshes odds and arbitrage calculations every 10 seconds

Data Processing
Advanced Team Matching: Uses fuzzy string matching to align teams across different providers

Normalization Engine: Standardizes team names for accurate comparison

Smart Data Merging: Prioritizes matches available on OrbitX exchange

User Interface
Interactive GUI: Built with Tkinter for easy monitoring

Visual Highlighting: Clearly marks arbitrage opportunities

Selective Monitoring: Choose which bookmakers to track

Technical Implementation
System Architecture
Chrome Automation: Uses Pyppeteer for browser control

Asynchronous Design: Non-blocking architecture for concurrent monitoring

Profile Management: Supports multiple Chrome user profiles

Data Processing Pipeline
Data Collection: Scrapes odds from each provider

Normalization: Standardizes team names and odds formats

Matching: Aligns equivalent matches across providers

Arbitrage Calculation: Identifies profitable opportunities
