import re
import time
from datetime import date, timedelta

from chatbot import tools
from services.anomaly_service import sales_anomalies
from services.forecast_service import revenue_forecast


def _product_phrase(question):
    match = re.search(r"(.+?)\s+(?:ఎన్ని|कितने|எத்தனை|ಎಷ್ಟು)(?:\s+.*)?$", question.strip(), re.I)
    if match:
        return match.group(1).strip(" ?.,")
    match = re.search(r"how many\s+(.+?)(?:\s+are\s+there|\s+do\s+we\s+have|\s+in\s+stock|\?|$)", question, re.I)
    if match:
        return match.group(1).strip(" ?.,")
    match = re.search(r"(?:stock|price|details?|sold|sales|revenue|profit|category|of|for)\s+(?:of\s+)?(.+?)(?:\s+(?:are|is|do|did|have|generate|in)\b|\?|$)", question, re.I)
    if match:
        value = match.group(1).strip(" ?.,")
        value = re.sub(r"^(?:the|a|an)\s+", "", value, flags=re.I)
        return value
    return None


def detect_intent(question):
    text = question.casefold()
    product = _product_phrase(question)
    if product and any(word in text for word in ("stock", "how many", "inventory", "reorder", "low", "ఎన్ని", "कितने", "எத்தனை", "ಎಷ್ಟು")):
        intent = "PRODUCT_STOCK"
    elif product and any(word in text for word in ("price", "cost")):
        intent = "PRODUCT_PRICE"
    elif product and any(word in text for word in ("sold", "units")):
        intent = "PRODUCT_SALES"
    elif product and "revenue" in text:
        intent = "PRODUCT_REVENUE"
    elif product and "profit" in text:
        intent = "PRODUCT_PROFIT"
    elif product and "category" in text:
        intent = "PRODUCT_DETAILS"
    elif any(word in text for word in ("out of stock", "zero stock", "స్టాక్ లేదు", "स्टॉक खत्म", "சரக்கு இல்லை", "ಸ್ಟಾಕ್ ಇಲ್ಲ")):
        intent = "OUT_OF_STOCK"
    elif any(word in text for word in ("low stock", "low in stock", "below reorder", "need restocking", "restock", "reorder", "తక్కువ స్టాక్", "कम स्टॉक", "குறைந்த சரக்கு", "ಕಡಿಮೆ ಸ್ಟಾಕ್")):
        intent = "LOW_STOCK"
    elif any(word in text for word in ("top customer", "best customer")):
        intent = "CUSTOMER_SUMMARY"
    elif any(word in text for word in ("purchase history", "purchases")):
        intent = "CUSTOMER_PURCHASES"
    elif any(word in text for word in ("how many customers", "customer details")):
        intent = "CUSTOMER_SUMMARY"
    elif any(word in text for word in ("customer", "spent")):
        intent = "CUSTOMER_DETAILS"
    elif any(word in text for word in ("forecast", "projection", "demand")):
        intent = "PRODUCT_FORECAST" if product else "FORECAST"
    elif any(word in text for word in ("anomal", "unusual", "abnormal", "అసాధారణ", "असामान्य", "அசாதாரண", "ಅಸಾಮಾನ್ಯ")):
        intent = "ANOMALY"
    elif any(word in text for word in ("profit", "profitable", "లాభ", "लाभ", "இலாப", "ಲಾಭ")):
        intent = "PROFIT_SUMMARY"
    elif any(word in text for word in ("top categor", "highest category")):
        intent = "TOP_CATEGORIES"
    elif any(word in text for word in ("top product", "top selling", "sold the most", "best selling", "most sold", "highest selling")):
        intent = "TOP_PRODUCTS"
    elif any(word in text for word in ("transaction", "transactions", "orders", "order count")):
        intent = "TRANSACTIONS"
    elif any(word in text for word in ("inventory", "how much stock")):
        intent = "INVENTORY_SUMMARY"
    elif any(word in text for word in ("sales", "revenue", "selling", "అమ్మకాలు", "बिक्री", "விற்பனை", "ಮಾರಾಟ")):
        intent = "SALES_BY_DATE" if any(word in text for word in ("today", "yesterday")) else "TOTAL_SALES"
    elif any(word in text for word in ("business summary", "how is business", "business overview", "summarize my business")):
        intent = "BUSINESS_SUMMARY"
    else:
        intent = "UNKNOWN"
    return {"intent": intent, "product_name": product}


def _period(question):
    today = date.today()
    text = question.casefold()
    if "yesterday" in text:
        target = today - timedelta(days=1)
        return tools.get_sales_for_date(target.isoformat()), "yesterday"
    if "today" in text:
        return tools.get_sales_for_date(today.isoformat()), "today"
    if "this month" in text:
        start = today.replace(day=1)
        end = (start.replace(day=28) + timedelta(days=4)).replace(day=1)
        return tools.get_sales_for_period(start.isoformat(), end.isoformat()), "this month"
    return tools.get_total_sales(), "recorded"


def _product_result(matches, requested):
    if not matches:
        return f"I couldn't find a product named '{requested}' in SalesNexa."
    if len(matches) > 1:
        return "I found multiple matching products: " + "; ".join(row["name"] for row in matches) + ". Which product do you mean?"
    return matches[0]


def answer_question(question, language="en", previous_product=None):
    started = time.perf_counter()
    details = detect_intent(question)
    product_name = details["product_name"] or previous_product
    if previous_product and not details["product_name"] and any(word in question.casefold() for word in ("that", "it", "this", "low", "stock")):
        details["intent"] = "PRODUCT_STOCK"
        product_name = previous_product
    if details["intent"] == "PRODUCT_STOCK" and not product_name:
        product_name = question
    intent = details["intent"]
    if intent in ("PRODUCT_STOCK", "PRODUCT_PRICE", "PRODUCT_DETAILS", "PRODUCT_SALES", "PRODUCT_REVENUE", "PRODUCT_PROFIT", "PRODUCT_FORECAST"):
        matches = tools.find_products(product_name or "")
        selected = _product_result(matches, product_name or question)
        if not isinstance(selected, str):
            if intent == "PRODUCT_STOCK":
                answer = f"{selected['name']} currently has {selected['quantity']} units in stock. It is {'low' if selected['quantity'] <= selected['reorder_level'] else 'not low'} in stock."
            elif intent == "PRODUCT_PRICE": answer = f"{selected['name']} sells for Rs {selected['selling_price']:.2f}."
            elif intent == "PRODUCT_DETAILS": answer = f"{selected['name']} is in the {selected['category'] or 'uncategorized'} category. SKU: {selected['sku']}. {selected['description'] or ''}".strip()
            elif intent == "PRODUCT_SALES":
                result = tools.get_product_sales(product_name); answer = f"{result['name']} has sold {result['units']} units."
            elif intent == "PRODUCT_REVENUE":
                result = tools.get_product_revenue(product_name); answer = f"{result['name']} generated Rs {result['revenue']:.2f} in revenue."
            elif intent == "PRODUCT_PROFIT":
                result = tools.get_product_profit(product_name); answer = f"{result['name']} generated Rs {result['profit']:.2f} in profit."
            else: answer = "There isn't enough product history to generate a reliable product forecast."
        else: answer = selected
    elif intent == "LOW_STOCK":
        rows = tools.get_low_stock_products(); answer = "Low-stock products: " + (", ".join(f"{row['name']} ({row['quantity']} units)" for row in rows) if rows else "none currently detected.")
    elif intent == "OUT_OF_STOCK":
        rows = tools.get_out_of_stock_products(); answer = "Out-of-stock products: " + (", ".join(row["name"] for row in rows) if rows else "none currently detected.")
    elif intent == "INVENTORY_SUMMARY":
        result = tools.get_inventory_summary(); answer = f"Inventory contains {result['products']} products and {result['units']} units, valued at Rs {result['value']:.2f}."
    elif intent in ("SALES_BY_DATE", "TOTAL_SALES"):
        result, period = _period(question); answer = f"{period.title()} sales are Rs {result['value']:.2f} across {result['orders']} orders." if result["orders"] else f"There are no sales records for {period}."
    elif intent == "TRANSACTIONS":
        result, period = _period(question); answer = f"There were {result['orders']} transactions for {period}."
    elif intent == "TOP_PRODUCTS":
        rows = tools.get_top_products(); answer = "Top products: " + (", ".join(f"{row['name']} ({row['units']} units)" for row in rows) if rows else "no sales data available.")
    elif intent == "TOP_CATEGORIES":
        rows = tools.get_top_categories(); answer = "Top categories: " + (", ".join(f"{row['name']} (Rs {row['revenue']:.2f})" for row in rows) if rows else "no sales data available.")
    elif intent == "PROFIT_SUMMARY":
        result = tools.get_profit_summary(); answer = f"Recorded revenue is Rs {result['revenue']:.2f} and profit is Rs {result['profit']:.2f}."
    elif intent == "FORECAST":
        result = revenue_forecast(); answer = result.get("message") or f"The next forecast values are {', '.join('Rs %.2f' % value for value in result['forecast'])}."
    elif intent == "ANOMALY":
        rows = sales_anomalies(); answer = "Unusual sales activity detected: " + (", ".join(f"sale #{row['sale_id']} (Rs {row['actual']:.2f})" for row in rows) if rows else "none detected.")
    elif intent == "CUSTOMER_SUMMARY":
        result = tools.get_customer_summary(); answer = f"SalesNexa has {result['customers']} customers."
    elif intent in ("CUSTOMER_DETAILS", "CUSTOMER_PURCHASES"):
        name = re.sub(r".*?(?:customer|client)\s+", "", question, flags=re.I).strip(" ?")
        rows = tools.get_customer_purchase_history(name) if intent == "CUSTOMER_PURCHASES" else tools.get_customer_details(name)
        answer = f"I found {len(rows)} matching customer record(s) for '{name}'." if rows else f"I couldn't find a customer named '{name}'."
    elif intent == "BUSINESS_SUMMARY":
        sales = tools.get_total_sales(); profit = tools.get_profit_summary(); inventory = tools.get_inventory_summary(); answer = f"Business summary: revenue Rs {sales['value']:.2f}, {sales['orders']} orders, profit Rs {profit['profit']:.2f}, {inventory['units']} inventory units, and {len(tools.get_low_stock_products())} low-stock alerts."
    else:
        answer = "I can only answer questions using the business data and analytics available in SalesNexa."
    return answer, details, round((time.perf_counter() - started) * 1000, 2), product_name