"""Test to check if IB provides Market Rules for BAG (combo) contracts.

This test requires a live TWS/Gateway connection to run.
Run with: pytest tests/ib/contract/test_bag_market_rules.py -v -s

The goal is to determine if IB provides:
1. ContractDetails for BAG contracts
2. Market Rules specifically for combos/spreads
3. Different tick sizes for spreads vs single legs
"""
import pytest
from ib_insync import IB, Contract, ComboLeg, Option


# Skip all tests if no TWS connection available
pytestmark = pytest.mark.skipif(
    True,  # Set to False to run with live TWS
    reason="Requires live TWS/Gateway connection"
)


@pytest.fixture(scope="module")
def ib():
    """Connect to TWS/Gateway."""
    ib = IB()
    try:
        ib.connect('127.0.0.1', 7497, clientId=99)  # Paper trading port
        yield ib
    finally:
        ib.disconnect()


class TestBAGMarketRules:
    """Test Market Rules for BAG (combo) contracts."""

    def test_single_leg_spx_option_market_rule(self, ib):
        """Get market rule for a single SPX option leg."""
        # Create a simple SPX option contract
        contract = Option(
            symbol='SPX',
            lastTradeDateOrContractMonth='20241220',  # Adjust date as needed
            strike=6000,
            right='C',
            exchange='SMART',
            currency='USD'
        )

        # Qualify the contract to get conId
        qualified = ib.qualifyContracts(contract)
        assert qualified, "Could not qualify SPX option contract"
        contract = qualified[0]

        print(f"\n=== Single Leg SPX Option ===")
        print(f"conId: {contract.conId}")
        print(f"symbol: {contract.symbol}")
        print(f"secType: {contract.secType}")
        print(f"exchange: {contract.exchange}")

        # Get contract details
        details = ib.reqContractDetails(contract)
        assert details, "No contract details returned"

        cd = details[0]
        print(f"\nContractDetails:")
        print(f"  minTick: {cd.minTick}")
        print(f"  validExchanges: {cd.validExchanges}")
        print(f"  marketRuleIds: {cd.marketRuleIds}")

        # Get market rule
        rule_ids = cd.marketRuleIds.split(',')
        if rule_ids and rule_ids[0]:
            rule_id = int(rule_ids[0])
            rule = ib.reqMarketRule(rule_id)
            print(f"\nMarket Rule {rule_id}:")
            for pr in rule:
                print(f"  lowEdge >= ${pr.lowEdge}: increment = {pr.increment}")

    def test_bag_contract_details(self, ib):
        """Try to get ContractDetails for a BAG (combo) contract."""
        # First, get two SPX option contracts for the spread
        call_low = Option(
            symbol='SPX',
            lastTradeDateOrContractMonth='20241220',
            strike=5900,
            right='C',
            exchange='SMART'
        )
        call_high = Option(
            symbol='SPX',
            lastTradeDateOrContractMonth='20241220',
            strike=6000,
            right='C',
            exchange='SMART'
        )

        # Qualify contracts
        qualified = ib.qualifyContracts(call_low, call_high)
        assert len(qualified) == 2, "Could not qualify both contracts"
        call_low, call_high = qualified

        print(f"\n=== BAG Contract (Bull Call Spread) ===")
        print(f"Leg 1: {call_low.symbol} {call_low.strike}C conId={call_low.conId}")
        print(f"Leg 2: {call_high.symbol} {call_high.strike}C conId={call_high.conId}")

        # Create BAG contract
        bag = Contract()
        bag.symbol = 'SPX'
        bag.secType = 'BAG'
        bag.currency = 'USD'
        bag.exchange = 'SMART'

        leg1 = ComboLeg()
        leg1.conId = call_low.conId
        leg1.ratio = 1
        leg1.action = 'BUY'
        leg1.exchange = 'SMART'

        leg2 = ComboLeg()
        leg2.conId = call_high.conId
        leg2.ratio = 1
        leg2.action = 'SELL'
        leg2.exchange = 'SMART'

        bag.comboLegs = [leg1, leg2]

        print(f"\nBAG contract created:")
        print(f"  symbol: {bag.symbol}")
        print(f"  secType: {bag.secType}")
        print(f"  exchange: {bag.exchange}")
        print(f"  comboLegs: {len(bag.comboLegs)} legs")

        # Try to get contract details for BAG
        print(f"\nTrying reqContractDetails for BAG...")
        try:
            details = ib.reqContractDetails(bag)
            if details:
                cd = details[0]
                print(f"SUCCESS! ContractDetails returned:")
                print(f"  minTick: {cd.minTick}")
                print(f"  validExchanges: {cd.validExchanges}")
                print(f"  marketRuleIds: {cd.marketRuleIds}")

                # Try to get market rule
                if cd.marketRuleIds:
                    rule_ids = cd.marketRuleIds.split(',')
                    if rule_ids and rule_ids[0]:
                        rule_id = int(rule_ids[0])
                        rule = ib.reqMarketRule(rule_id)
                        print(f"\nMarket Rule {rule_id} for BAG:")
                        for pr in rule:
                            print(f"  lowEdge >= ${pr.lowEdge}: increment = {pr.increment}")
            else:
                print("No ContractDetails returned for BAG (empty list)")
        except Exception as e:
            print(f"ERROR getting ContractDetails for BAG: {e}")

    def test_compare_single_vs_bag_tick(self, ib):
        """Compare tick sizes between single leg and BAG."""
        # Get single leg
        option = Option(
            symbol='SPX',
            lastTradeDateOrContractMonth='20241220',
            strike=6000,
            right='C',
            exchange='SMART'
        )
        qualified = ib.qualifyContracts(option)
        option = qualified[0]

        single_details = ib.reqContractDetails(option)
        single_tick = single_details[0].minTick if single_details else None

        print(f"\n=== Tick Size Comparison ===")
        print(f"Single leg minTick: {single_tick}")

        # Create BAG
        call_low = Option('SPX', '20241220', 5900, 'C', 'SMART')
        call_high = Option('SPX', '20241220', 6000, 'C', 'SMART')
        qualified = ib.qualifyContracts(call_low, call_high)

        bag = Contract()
        bag.symbol = 'SPX'
        bag.secType = 'BAG'
        bag.currency = 'USD'
        bag.exchange = 'SMART'

        leg1 = ComboLeg()
        leg1.conId = qualified[0].conId
        leg1.ratio = 1
        leg1.action = 'BUY'
        leg1.exchange = 'SMART'

        leg2 = ComboLeg()
        leg2.conId = qualified[1].conId
        leg2.ratio = 1
        leg2.action = 'SELL'
        leg2.exchange = 'SMART'

        bag.comboLegs = [leg1, leg2]

        try:
            bag_details = ib.reqContractDetails(bag)
            bag_tick = bag_details[0].minTick if bag_details else None
            print(f"BAG minTick: {bag_tick}")

            if single_tick and bag_tick:
                if single_tick != bag_tick:
                    print(f"DIFFERENT! Single={single_tick}, BAG={bag_tick}")
                else:
                    print(f"SAME tick size for single and BAG")
        except Exception as e:
            print(f"Could not get BAG details: {e}")
            print("IB does NOT provide ContractDetails for BAG contracts")


class TestDifferentUnderlyings:
    """Test market rules for different underlyings."""

    @pytest.mark.parametrize("symbol,exchange,strike,expiry", [
        ("SPX", "SMART", 6000, "20241220"),
        ("TSLA", "SMART", 400, "20241220"),
        # ("DAX", "EUREX", 20000, "20241220"),  # Needs different contract setup
    ])
    def test_option_market_rules(self, ib, symbol, exchange, strike, expiry):
        """Get market rules for different option underlyings."""
        contract = Option(
            symbol=symbol,
            lastTradeDateOrContractMonth=expiry,
            strike=strike,
            right='C',
            exchange=exchange,
            currency='USD' if symbol != 'DAX' else 'EUR'
        )

        try:
            qualified = ib.qualifyContracts(contract)
            if not qualified:
                print(f"\n{symbol}: Could not qualify contract")
                return

            contract = qualified[0]
            details = ib.reqContractDetails(contract)

            if not details:
                print(f"\n{symbol}: No contract details")
                return

            cd = details[0]
            print(f"\n=== {symbol} Option ===")
            print(f"minTick: {cd.minTick}")
            print(f"validExchanges: {cd.validExchanges[:50]}...")
            print(f"marketRuleIds: {cd.marketRuleIds[:50]}...")

            # Get first market rule
            rule_ids = cd.marketRuleIds.split(',')
            if rule_ids and rule_ids[0]:
                rule_id = int(rule_ids[0])
                rule = ib.reqMarketRule(rule_id)
                print(f"Market Rule {rule_id}:")
                for pr in rule:
                    print(f"  >= ${pr.lowEdge}: {pr.increment}")

        except Exception as e:
            print(f"\n{symbol}: Error - {e}")


if __name__ == "__main__":
    # Run manually without pytest
    ib = IB()
    ib.connect('127.0.0.1', 7497, clientId=99)

    try:
        test = TestBAGMarketRules()
        test.test_single_leg_spx_option_market_rule(ib)
        test.test_bag_contract_details(ib)
        test.test_compare_single_vs_bag_tick(ib)
    finally:
        ib.disconnect()
