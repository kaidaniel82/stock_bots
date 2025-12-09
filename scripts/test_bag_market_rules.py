#!/usr/bin/env python3
"""
Test script to check if IB provides Market Rules for BAG (combo) contracts.

Run with TWS/Gateway running:
    python scripts/test_bag_market_rules.py

This will test:
1. Single leg contract details and market rules (from portfolio)
2. BAG (combo) contract details and market rules
3. Compare tick sizes between single and combo
"""
from ib_insync import IB, Contract, ComboLeg
import sys


def test_single_leg_by_conid(ib: IB, con_id: int):
    """Test single leg market rules using conId."""
    print(f"\n{'='*60}")
    print(f"SINGLE LEG: conId={con_id}")
    print('='*60)

    contract = Contract(conId=con_id)
    qualified = ib.qualifyContracts(contract)

    if not qualified:
        print(f"ERROR: Could not qualify conId={con_id}")
        return None, None

    contract = qualified[0]
    print(f"symbol: {contract.symbol}")
    print(f"secType: {contract.secType}")
    print(f"strike: {contract.strike}")
    print(f"right: {contract.right}")
    print(f"expiry: {contract.lastTradeDateOrContractMonth}")
    print(f"exchange: {contract.exchange}")

    details = ib.reqContractDetails(contract)
    if not details:
        print("ERROR: No contract details")
        return contract, None

    cd = details[0]
    print(f"\nContractDetails:")
    print(f"  minTick: {cd.minTick}")
    print(f"  validExchanges: {cd.validExchanges}")
    print(f"  marketRuleIds: {cd.marketRuleIds}")

    # Get market rules
    rule_ids = (cd.marketRuleIds or "").split(',')
    if rule_ids and rule_ids[0]:
        rule_id = int(rule_ids[0])
        rule = ib.reqMarketRule(rule_id)
        print(f"\nMarket Rule {rule_id}:")
        for pr in rule:
            print(f"  >= ${pr.lowEdge:.2f}: tick = {pr.increment}")

    return contract, cd


def test_bag_from_conids(ib: IB, con_id1: int, con_id2: int, symbol: str, exchange: str = "SMART"):
    """Test BAG (combo) contract details using conIds."""
    print(f"\n{'='*60}")
    print(f"BAG CONTRACT: {symbol} conIds={con_id1},{con_id2}")
    print('='*60)

    # Qualify leg contracts
    leg1_contract = Contract(conId=con_id1)
    leg2_contract = Contract(conId=con_id2)

    qualified = ib.qualifyContracts(leg1_contract, leg2_contract)
    if len(qualified) != 2:
        print("ERROR: Could not qualify both legs")
        return None

    leg1_contract, leg2_contract = qualified
    print(f"Leg 1: {leg1_contract.symbol} {leg1_contract.strike}{leg1_contract.right} conId={leg1_contract.conId}")
    print(f"Leg 2: {leg2_contract.symbol} {leg2_contract.strike}{leg2_contract.right} conId={leg2_contract.conId}")

    # Create BAG contract
    bag = Contract()
    bag.symbol = symbol
    bag.secType = 'BAG'
    bag.currency = leg1_contract.currency
    bag.exchange = exchange

    leg1 = ComboLeg()
    leg1.conId = con_id1
    leg1.ratio = 1
    leg1.action = 'BUY'
    leg1.exchange = exchange

    leg2 = ComboLeg()
    leg2.conId = con_id2
    leg2.ratio = 1
    leg2.action = 'SELL'
    leg2.exchange = exchange

    bag.comboLegs = [leg1, leg2]

    print(f"\nBAG contract:")
    print(f"  secType: {bag.secType}")
    print(f"  exchange: {bag.exchange}")
    print(f"  legs: {len(bag.comboLegs)}")

    # Try to get contract details
    print(f"\nTrying reqContractDetails(BAG)...")
    try:
        details = ib.reqContractDetails(bag)
        if details:
            cd = details[0]
            print(f"\n*** SUCCESS! IB returns ContractDetails for BAG ***")
            print(f"  minTick: {cd.minTick}")
            print(f"  validExchanges: {cd.validExchanges}")
            print(f"  marketRuleIds: {cd.marketRuleIds}")

            # Try market rule
            if cd.marketRuleIds:
                rule_ids = cd.marketRuleIds.split(',')
                if rule_ids and rule_ids[0]:
                    try:
                        rule_id = int(rule_ids[0])
                        rule = ib.reqMarketRule(rule_id)
                        print(f"\nMarket Rule {rule_id} for BAG:")
                        for pr in rule:
                            print(f"  >= ${pr.lowEdge:.2f}: tick = {pr.increment}")
                    except ValueError:
                        print(f"  Could not parse rule_id: {rule_ids[0]}")
            return cd
        else:
            print("\n*** IB returns EMPTY list for BAG ContractDetails ***")
            print("This means we need a lookup table for combo tick sizes")
            return None
    except Exception as e:
        print(f"\n*** ERROR: {e} ***")
        print("IB does NOT support ContractDetails for BAG contracts")
        return None


def test_from_portfolio(ib: IB):
    """Test using positions from the portfolio."""
    print(f"\n{'='*60}")
    print("READING PORTFOLIO POSITIONS")
    print('='*60)

    positions = ib.positions()
    if not positions:
        print("No positions found in portfolio")
        return

    # Group by symbol
    by_symbol = {}
    for pos in positions:
        sym = pos.contract.symbol
        if sym not in by_symbol:
            by_symbol[sym] = []
        by_symbol[sym].append(pos)

    print(f"Found {len(positions)} positions in {len(by_symbol)} symbols")

    for sym, pos_list in by_symbol.items():
        if len(pos_list) >= 2:
            print(f"\n{sym}: {len(pos_list)} positions (can test BAG)")
            for p in pos_list:
                c = p.contract
                print(f"  conId={c.conId} {c.strike}{c.right} qty={p.position}")
        else:
            print(f"\n{sym}: {len(pos_list)} position (single leg only)")

    return by_symbol




def main():
    print("Connecting to TWS/Gateway...")
    ib = IB()

    try:
        # Try paper trading port first, then live
        try:
            ib.connect('127.0.0.1', 7497, clientId=99)
        except:
            ib.connect('127.0.0.1', 7496, clientId=99)

        print(f"Connected! Server version: {ib.client.serverVersion()}")

        # First, show portfolio positions
        by_symbol = test_from_portfolio(ib)

        if not by_symbol:
            print("\nNo portfolio - testing with known conIds from logs...")
            # Known SPX conIds from your logs
            spx_con_ids = [834873648, 834873658]
        else:
            # Use first symbol with 2+ positions
            for sym, pos_list in by_symbol.items():
                if len(pos_list) >= 2:
                    spx_con_ids = [p.contract.conId for p in pos_list[:2]]
                    symbol = sym
                    exchange = pos_list[0].contract.exchange or "SMART"
                    break
            else:
                print("\nNo symbol with 2+ positions for BAG test")
                spx_con_ids = []

        if len(spx_con_ids) >= 2:
            # Test single leg
            contract1, cd1 = test_single_leg_by_conid(ib, spx_con_ids[0])
            contract2, cd2 = test_single_leg_by_conid(ib, spx_con_ids[1])

            if contract1 and contract2:
                symbol = contract1.symbol
                # Determine exchange - use primary exchange or CBOE for SPX
                if symbol == 'SPX':
                    exchange = 'CBOE'
                else:
                    exchange = contract1.exchange or 'SMART'

                # Test BAG
                bag_cd = test_bag_from_conids(ib, spx_con_ids[0], spx_con_ids[1], symbol, exchange)

                # Summary
                print(f"\n{'='*60}")
                print("SUMMARY")
                print('='*60)
                if cd1:
                    print(f"Single leg 1 minTick: {cd1.minTick}")
                if cd2:
                    print(f"Single leg 2 minTick: {cd2.minTick}")
                if bag_cd:
                    print(f"BAG minTick: {bag_cd.minTick}")
                    if cd1 and bag_cd.minTick != cd1.minTick:
                        print(f"\n*** DIFFERENT TICK SIZES! ***")
                        print(f"Single: {cd1.minTick}, BAG: {bag_cd.minTick}")
                else:
                    print(f"BAG: No ContractDetails - IB does not provide this!")
                    print(f"\n*** CONCLUSION: Need lookup table for combo tick sizes ***")

    except Exception as e:
        print(f"ERROR: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
    finally:
        ib.disconnect()
        print("\nDisconnected.")





if __name__ == "__main__":
    main()
