def calculate_subtotal(items):
    total = 0
    for item in items:
        total = total + item["price"] * item["quantity"]  
    return total


def apply_discount(subtotal, discount_code):
    discounts = {
        "SAVE10": 0.10,
        "SAVE20": 0.20,
    }
    if discount_code in discounts:
        # BUG FIX: return discounted amount (subtotal - discount_amount) instead of discount amount itself
        discount_amount = subtotal * discounts[discount_code]
        return subtotal - discount_amount
    return subtotal


def calculate_tax(amount, tax_rate=0.08):
    return amount * tax_rate


def print_receipt(items, discount_code=None):
    subtotal = calculate_subtotal(items)

    if discount_code:
        subtotal = apply_discount(subtotal, discount_code)  

    tax = calculate_tax(subtotal)
    total = subtotal + tax

    print("---- RECEIPT ----")
    for item in items:
        line_total = item["price"] * item["quantity"]
        print(f"{item['name']:<15} x{item['quantity']:<3} ${line_total:.2f}")
    print("-----------------")
    print(f"Subtotal: ${subtotal:.2f}")
    print(f"Tax:      ${tax:.2f}")
    print(f"Total:    ${total:.2f}")
    return total


def find_item_by_name(items, name):
    for item in items:
        if item["name"] == name:
            return item
    return None
    


if __name__ == "__main__":
    cart = [
        {"name": "Widget", "price": 9.99, "quantity": 3},
        {"name": "Gadget", "price": 24.50, "quantity": 1},
        {"name": "Gizmo", "price": 4.75, "quantity": 5},
    ]

    print_receipt(cart, discount_code="SAVE10")

    found = find_item_by_name(cart, "Doohickey")  
    if found:
        print(f"Found item price: {found['price']}")
    else:
        print("Item 'Doohickey' not found.")
