from ib_insync import IB, Contract, ComboLeg
import sys



def main2():
    ib = IB()
    ib.connect('127.0.0.1', 7497, clientId=1)  # TWS oder IBGW
    spx_con_ids = [834873648, 834873658]
    # ⚠️ conId-Werte durch echte Contract-IDs deiner Legs ersetzen!
    leg1 = ComboLeg(conId=spx_con_ids[0], ratio=1, action='BUY', exchange='SMART')
    leg2 = ComboLeg(conId=spx_con_ids[2], ratio=1, action='SELL', exchange='SMART')

    combo = Contract(
        symbol='SPY',  # nur symbolisch; muss zu den Legs passen
        secType='BAG',
        currency='USD',
        exchange='SMART',
        comboLegs=[leg1, leg2]
    )

    details_list = ib.reqContractDetails(combo)

    for d in details_list:
        print('Contract:', d.contract)
        print('MarketName:', d.marketName)
        print('MinTick:', d.minTick)
        print('-' * 40)

    ib.disconnect()

if __name__ == '__main__':
    main2()
