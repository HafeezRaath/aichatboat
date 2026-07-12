from fastapi import FastAPI, File, UploadFile, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from typing import Optional, List, Dict, Any
import json
import os
import re
import base64
import uuid
from datetime import datetime, timedelta
import httpx

# ============ CONFIGURATION ============
SHOPIFY_SHOP_DOMAIN = os.getenv("SHOPIFY_SHOP_DOMAIN", "your-store.myshopify.com")
SHOPIFY_ADMIN_API_TOKEN = os.getenv("SHOPIFY_ADMIN_API_TOKEN", "")
SHOPIFY_STOREFRONT_ACCESS_TOKEN = os.getenv("SHOPIFY_STOREFRONT_ACCESS_TOKEN", "")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
SHOPIFY_CLIENT_ID = os.getenv("SHOPIFY_CLIENT_ID", "")
SHOPIFY_CLIENT_SECRET = os.getenv("SHOPIFY_CLIENT_SECRET", "")

SHOPIFY_SHOP_DOMAIN = SHOPIFY_SHOP_DOMAIN.rstrip('/')

print("=" * 60)
print("CONFIG LOADED:")
print("  SHOPIFY_SHOP_DOMAIN:", SHOPIFY_SHOP_DOMAIN)
print("  ADMIN_TOKEN set:", bool(SHOPIFY_ADMIN_API_TOKEN))
print("  STOREFRONT_TOKEN set:", bool(SHOPIFY_STOREFRONT_ACCESS_TOKEN))
print("  OPENAI_KEY set:", bool(OPENAI_API_KEY))
print("=" * 60)

app = FastAPI(title="REZON AI VTON Engine", version="4.0.0")

# ============ CORS ============
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ============ CATEGORIES ============
CATEGORIES = [
    {
        "id": "unstitched",
        "name": "Unstitched Fabric",
        "name_urdu": "Unstitched Fabric",
        "image": "https://images.unsplash.com/photo-1596755094514-f87e34085b2c?w=400&h=400&fit=crop",
        "description": "Premium cotton, lawn, and wash & wear fabrics"
    },
    {
        "id": "perfumes",
        "name": "Perfumes",
        "name_urdu": "Perfumes",
        "image": "https://images.unsplash.com/photo-1541643600914-78a084cdc566?w=400&h=400&fit=crop",
        "description": "Luxury oud and premium fragrances"
    },
    {
        "id": "wallets",
        "name": "Wallets",
        "name_urdu": "Wallets",
        "image": "https://images.unsplash.com/photo-1627123424574-724758594e93?w=400&h=400&fit=crop",
        "description": "Genuine leather wallets and card holders"
    },
    {
        "id": "gifts",
        "name": "Gift Boxes",
        "name_urdu": "Gift Boxes",
        "image": "https://images.unsplash.com/photo-1512909006721-3d6018887383?w=400&h=400&fit=crop",
        "description": "Curated gift sets for special occasions"
    }
]

# ============ MOCK PRODUCTS (Real Images) ============
MOCK_PRODUCTS = [
    {
        "id": "gid://shopify/Product/1",
        "title": "Premium Grey Unstitched Suit",
        "description": "High quality unstitched fabric perfect for summer suits. Soft cotton blend with elegant texture. 4.5 meter cutting with matching dupatta piece.",
        "handle": "premium-unstitched-fabric-grey",
        "price": "5990.00",
        "compare_at_price": "7500.00",
        "currency": "PKR",
        "image_url": "https://images.unsplash.com/photo-1596755094514-f87e34085b2c?w=400&h=400&fit=crop",
        "variant_id": "gid://shopify/ProductVariant/1",
        "numeric_variant_id": "1",
        "category": "unstitched",
        "tags": ["unstitched", "cotton", "summer", "grey"],
        "discount_percent": 20,
        "features": ["Pure cotton blend", "4.5 meter suit cutting", "Soft & breathable", "Easy to stitch"]
    },
    {
        "id": "gid://shopify/Product/2",
        "title": "Classic Black Wash & Wear",
        "description": "Easy maintenance wash and wear fabric. Perfect for daily office wear and formal occasions. Wrinkle-free technology.",
        "handle": "wash-wear-black",
        "price": "4950.00",
        "compare_at_price": "6200.00",
        "currency": "PKR",
        "image_url": "https://images.unsplash.com/photo-1594938298603-c8148c4dae35?w=400&h=400&fit=crop",
        "variant_id": "gid://shopify/ProductVariant/2",
        "numeric_variant_id": "2",
        "category": "unstitched",
        "tags": ["wash-wear", "formal", "black", "wrinkle-free"],
        "discount_percent": 20,
        "features": ["Wrinkle-free fabric", "No ironing needed", "4 meter cutting", "Office wear perfect"]
    },
    {
        "id": "gid://shopify/Product/3",
        "title": "Summer Floral Lawn Collection",
        "description": "Breathable lawn fabric with beautiful floral print. Ideal for hot summer days. Digital print with color guarantee.",
        "handle": "summer-lawn-collection-floral",
        "price": "3990.00",
        "compare_at_price": "5500.00",
        "currency": "PKR",
        "image_url": "https://images.unsplash.com/photo-1572804013309-59a88b7e92f1?w=400&h=400&fit=crop",
        "variant_id": "gid://shopify/ProductVariant/3",
        "numeric_variant_id": "3",
        "category": "unstitched",
        "tags": ["lawn", "floral", "summer", "digital-print"],
        "discount_percent": 27,
        "features": ["Digital floral print", "Color fast guarantee", "Soft lawn fabric", "2 piece suit"]
    },
    {
        "id": "gid://shopify/Product/4",
        "title": "Luxury Oud Perfume Collection",
        "description": "Premium oud fragrance with long lasting scent. Perfect for special occasions. 100ml bottle with 24hr lasting power.",
        "handle": "luxury-perfume-oud",
        "price": "8500.00",
        "compare_at_price": "12000.00",
        "currency": "PKR",
        "image_url": "https://images.unsplash.com/photo-1541643600914-78a084cdc566?w=400&h=400&fit=crop",
        "variant_id": "gid://shopify/ProductVariant/4",
        "numeric_variant_id": "4",
        "category": "perfumes",
        "tags": ["perfume", "oud", "luxury", "100ml"],
        "discount_percent": 29,
        "features": ["Pure oud extract", "24 hours lasting", "100ml premium bottle", "Gift packaging"]
    },
    {
        "id": "gid://shopify/Product/5",
        "title": "Genuine Brown Leather Wallet",
        "description": "Genuine leather wallet with multiple card slots and coin pocket. Premium quality stitching. RFID protected.",
        "handle": "leather-wallet-brown",
        "price": "2950.00",
        "compare_at_price": "4200.00",
        "currency": "PKR",
        "image_url": "https://images.unsplash.com/photo-1627123424574-724758594e93?w=400&h=400&fit=crop",
        "variant_id": "gid://shopify/ProductVariant/5",
        "numeric_variant_id": "5",
        "category": "wallets",
        "tags": ["wallet", "leather", "brown", "rfid"],
        "discount_percent": 30,
        "features": ["100% genuine leather", "RFID protection", "8 card slots", "Coin pocket included"]
    },
    {
        "id": "gid://shopify/Product/6",
        "title": "Elegant Gift Box Set",
        "description": "Premium gift box with curated items. Perfect for birthdays, weddings, and special events. Includes wallet + perfume + keychain.",
        "handle": "elegant-gift-box-set",
        "price": "4500.00",
        "compare_at_price": "6000.00",
        "currency": "PKR",
        "image_url": "https://images.unsplash.com/photo-1512909006721-3d6018887383?w=400&h=400&fit=crop",
        "variant_id": "gid://shopify/ProductVariant/6",
        "numeric_variant_id": "6",
        "category": "gifts",
        "tags": ["gift", "box", "premium", "combo"],
        "discount_percent": 25,
        "features": ["Wallet + Perfume + Keychain", "Premium gift packaging", "Ready to gift", "Best value combo"]
    }
]

# ============ ROOT / HEALTH ============
@app.get("/")
async def root():
    return {"message": "REZON AI VTON Engine Running", "version": "4.0.0", "status": "ok"}

@app.get("/health")
async def health():
    return {"status": "healthy"}

# ============ MODELS ============
class ChatMessage(BaseModel):
    role: str
    content: str
    product_cards: Optional[List[Dict]] = None
    image_url: Optional[str] = None

class ChatRequest(BaseModel):
    messages: List[ChatMessage]
    session_id: str
    product_context: Optional[str] = None

class SimpleChatRequest(BaseModel):
    message: str
    session_id: Optional[str] = "default"

class DiscountRequest(BaseModel):
    percentage: float = 5.0
    customer_email: Optional[str] = None
    product_id: Optional[str] = None

class VTONRequest(BaseModel):
    user_image_url: str
    product_image_url: str
    product_id: str
    session_id: str

class ProductFetchRequest(BaseModel):
    query: Optional[str] = None
    product_id: Optional[str] = None
    category: Optional[str] = None
    limit: int = 10

class AddToCartRequest(BaseModel):
    variant_id: str
    quantity: int = 1

class CategoryRequest(BaseModel):
    category_id: Optional[str] = None

# ============ HTML STRIPPER ============
def strip_html(html_text):
    if not html_text:
        return ""
    clean = re.sub(r'<[^>]+>', '', html_text)
    clean = re.sub(r'\s+', ' ', clean).strip()
    return clean

# ============ SHOPIFY CLIENT ============
class ShopifyClient:
    def __init__(self, shop_domain: str, admin_token: str, storefront_token: str):
        self.shop_domain = shop_domain
        self.admin_url = f"https://{shop_domain}/admin/api/2024-07/graphql.json"
        self.admin_rest_url = f"https://{shop_domain}/admin/api/2024-07"
        self.storefront_url = f"https://{shop_domain}/api/2024-07/graphql.json"
        self.admin_headers = {
            "Content-Type": "application/json",
            "X-Shopify-Access-Token": admin_token
        }
        self.storefront_headers = {
            "Content-Type": "application/json",
            "X-Shopify-Storefront-Access-Token": storefront_token
        }

    def _calculate_discount(self, price_str, compare_str):
        try:
            price = float(price_str)
            compare = float(compare_str) if compare_str else 0
            if compare > price:
                return round(((compare - price) / compare) * 100)
        except:
            pass
        return 0

    def _format_product(self, p: dict, category: str = None) -> dict:
        """Format a product with all needed fields"""
        variant = p["variants"][0] if p.get("variants") else {}
        image = p["images"][0] if p.get("images") else {}

        price = variant.get("price", "0.00")
        compare = variant.get("compare_at_price")
        discount = self._calculate_discount(price, compare)

        variant_id_num = variant.get("id")
        variant_id_gid = f"gid://shopify/ProductVariant/{variant_id_num}" if variant_id_num else None

        # Determine category from tags/type
        tags = p.get("tags", [])
        product_type = p.get("product_type", "").lower()
        prod_category = category or "general"

        if any(t in ["perfume", "oud", "fragrance"] for t in [product_type] + [t.lower() for t in tags]):
            prod_category = "perfumes"
        elif any(t in ["wallet", "leather"] for t in [product_type] + [t.lower() for t in tags]):
            prod_category = "wallets"
        elif any(t in ["gift", "box", "combo"] for t in [product_type] + [t.lower() for t in tags]):
            prod_category = "gifts"
        elif any(t in ["fabric", "unstitched", "lawn", "cotton"] for t in [product_type] + [t.lower() for t in tags]):
            prod_category = "unstitched"

        return {
            "id": f"gid://shopify/Product/{p['id']}",
            "title": p["title"],
            "description": strip_html(p.get("body_html", ""))[:300],
            "handle": p["handle"],
            "price": price,
            "compare_at_price": compare,
            "currency": "PKR",
            "image_url": image.get("src") if image else None,
            "variant_id": variant_id_gid,
            "numeric_variant_id": str(variant_id_num) if variant_id_num else None,
            "category": prod_category,
            "tags": p.get("tags", []),
            "discount_percent": discount,
            "product_type": p.get("product_type", ""),
            "vendor": p.get("vendor", ""),
            "features": p.get("tags", [])[:4]  # Use tags as features fallback
        }

    async def fetch_products_admin_rest(self, query: str = None, category: str = None, limit: int = 10) -> List[Dict]:
        """Fetch REAL products from Shopify using Admin REST API"""
        if not self.admin_headers["X-Shopify-Access-Token"]:
            print("❌ ADMIN TOKEN NOT SET")
            return []

        url = f"{self.admin_rest_url}/products.json?limit={limit}&status=active"
        if query:
            url += f"&title={query}"

        print(f"🔍 Fetching real products: {url}")

        try:
            async with httpx.AsyncClient() as client:
                response = await client.get(url, headers=self.admin_headers, timeout=15.0)

            print(f"📡 Admin API Status: {response.status_code}")

            if response.status_code != 200:
                print(f"❌ Admin API Error: {response.text[:200]}")
                return []

            data = response.json()
            products = data.get("products", [])

            if not products:
                print("⚠️ No products found in your Shopify store")
                return []

            formatted = [self._format_product(p, category) for p in products]

            # Filter by category if specified
            if category:
                formatted = [p for p in formatted if p["category"] == category]

            print(f"✅ Fetched {len(formatted)} REAL products!")
            return formatted

        except Exception as e:
            print(f"❌ Admin REST API error: {e}")
            return []

    async def fetch_products(self, query: str = None, category: str = None, limit: int = 10) -> List[Dict]:
        """Smart fetch: Try REAL store products first, fallback to mock"""
        if self.admin_headers["X-Shopify-Access-Token"]:
            products = await self.fetch_products_admin_rest(query, category, limit)
            if products:
                return products

        # Fallback to mock products
        print("⚠️ Using MOCK products")
        products = MOCK_PRODUCTS
        if category:
            products = [p for p in products if p.get("category") == category]
        return products[:limit]

    async def create_cart(self, variant_id: str, quantity: int = 1) -> Dict:
        if not self.storefront_headers["X-Shopify-Storefront-Access-Token"]:
            return {"error": "No storefront token"}

        mutation = """
        mutation cartCreate($input: CartInput!) {
            cartCreate(input: $input) {
                cart {
                    id
                    checkoutUrl
                }
                userErrors {
                    field
                    message
                }
            }
        }
        """

        variables = {
            "input": {
                "lines": [{"quantity": quantity, "merchandiseId": variant_id}]
            }
        }

        try:
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    self.storefront_url,
                    headers=self.storefront_headers,
                    json={"query": mutation, "variables": variables},
                    timeout=10.0
                )
                return response.json()
        except Exception as e:
            print(f"Error creating cart: {e}")
            return {"error": str(e)}

shopify = ShopifyClient(SHOPIFY_SHOP_DOMAIN, SHOPIFY_ADMIN_API_TOKEN, SHOPIFY_STOREFRONT_ACCESS_TOKEN)

# ============ AI SERVICE ============
class AIService:
    def __init__(self, api_key: str):
        self.api_key = api_key
        self.url = "https://api.openai.com/v1/chat/completions"

    def _build_product_detail_prompt(self, product: Dict) -> str:
        """Build rich product explanation prompt"""
        features = product.get("features", [])
        features_text = "\n".join([f"- {f}" for f in features]) if features else ""

        discount_text = ""
        if product.get("discount_percent", 0) > 0:
            discount_text = f"\n🔥 SPECIAL OFFER: {product['discount_percent']}% OFF! Original price {product.get('compare_at_price', '')} PKR, now only {product['price']} PKR!"

        return f"""Product: {product['title']}
Price: {product['price']} PKR{discount_text}
Description: {product.get('description', '')}
Features:
{features_text}

Explain this product in Roman Urdu like a friendly salesman. Highlight:
1. Fabric/material quality
2. Best use cases (occasion, season)
3. Why it's worth buying
4. Discount value (if any)
5. End with "Add to Cart karein?" and emojis

Keep it under 150 words, exciting and persuasive."""

    async def explain_product(self, product: Dict) -> str:
        """Get AI explanation for a specific product"""
        prompt = self._build_product_detail_prompt(product)

        try:
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    self.url,
                    headers={"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"},
                    json={
                        "model": "gpt-4o-mini",
                        "messages": [
                            {"role": "system", "content": "You are REZON AI, a premium fashion assistant. Speak in Roman Urdu (Hinglish). Be friendly, persuasive, and concise."},
                            {"role": "user", "content": prompt}
                        ],
                        "temperature": 0.7,
                        "max_tokens": 300
                    },
                    timeout=15.0
                )

            result = response.json()
            if "choices" in result:
                return result["choices"][0]["message"].get("content", "")
            return self._fallback_explanation(product)

        except Exception as e:
            print(f"AI explain error: {e}")
            return self._fallback_explanation(product)

    def _fallback_explanation(self, product: Dict) -> str:
        """Fallback explanation if AI fails"""
        title = product.get("title", "")
        price = product.get("price", "")
        compare = product.get("compare_at_price", "")
        discount = product.get("discount_percent", 0)
        desc = product.get("description", "")[:100]

        msg = f"Yeh hamara {title} hai! "
        if desc:
            msg += f"{desc} "

        if discount > 0 and compare:
            msg += f"🔥 Abhi {discount}% OFF par mil raha hai! Sirf {price} PKR (was {compare} PKR). "
        else:
            msg += f"Price sirf {price} PKR. "

        msg += "Quality bohat zabardast hai. Add to Cart karein? 🛒"
        return msg

    async def chat_with_products(self, messages: List[Dict], products: List[Dict] = None, force_products: bool = False) -> Dict:
        system_prompt = """You are REZON AI, a premium fashion assistant for REZON store. 
Speak in Roman Urdu (Hinglish) when customer uses it.
Be friendly, concise, and helpful."""

        formatted_messages = [{"role": "system", "content": system_prompt}]
        for msg in messages:
            if isinstance(msg, dict):
                formatted_messages.append({"role": msg.get("role", "user"), "content": msg.get("content", "")})
            else:
                formatted_messages.append({"role": msg.role, "content": msg.content})

        tools = [
            {
                "type": "function",
                "function": {
                    "name": "show_products",
                    "description": "Show product cards to the user",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "message": {"type": "string", "description": "Message in Roman Urdu"}
                        },
                        "required": ["message"]
                    }
                }
            }
        ]

        try:
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    self.url,
                    headers={"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"},
                    json={
                        "model": "gpt-4o-mini",
                        "messages": formatted_messages,
                        "tools": tools,
                        "tool_choice": "auto" if not force_products else {"type": "function", "function": {"name": "show_products"}},
                        "temperature": 0.7,
                        "max_tokens": 500
                    },
                    timeout=20.0
                )

            result = response.json()
            if "choices" not in result:
                return {"text": "Sorry, AI service temporarily unavailable.", "tool_calls": None}

            message = result["choices"][0]["message"]
            return {
                "text": message.get("content", ""),
                "tool_calls": message.get("tool_calls")
            }

        except Exception as e:
            print("OpenAI error:", str(e))
            return {"text": "Sorry, AI service mein masla hai.", "tool_calls": None}

ai_service = AIService(OPENAI_API_KEY)

# ============ API ROUTES ============

# ====== GET CATEGORIES ======
@app.get("/api/categories")
async def get_categories():
    return {
        "success": True,
        "categories": CATEGORIES
    }

# ====== GET PRODUCTS BY CATEGORY ======
@app.post("/api/products")
async def get_products(request: ProductFetchRequest):
    try:
        products = await shopify.fetch_products(
            query=request.query,
            category=request.category,
            limit=request.limit
        )
        return {
            "success": True,
            "products": products,
            "category": request.category
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# ====== GET PRODUCT DETAIL (AI EXPLANATION) ======
@app.post("/api/product/explain")
async def explain_product_endpoint(request: ProductFetchRequest):
    try:
        # Find product
        products = await shopify.fetch_products(limit=50)
        product = None
        for p in products:
            if p["id"] == request.product_id or p["handle"] == request.product_id:
                product = p
                break

        if not product:
            # Try mock products
            for p in MOCK_PRODUCTS:
                if p["id"] == request.product_id or p["handle"] == request.product_id:
                    product = p
                    break

        if not product:
            raise HTTPException(status_code=404, detail="Product not found")

        # Get AI explanation
        explanation = await ai_service.explain_product(product)

        return {
            "success": True,
            "product": product,
            "explanation": explanation,
            "quick_replies": ["Add to Cart", "Aur products dekhein", "Discount code chahiye", "Styling tips"]
        }

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# ====== ADD TO CART ======
@app.post("/api/cart/add")
async def add_to_cart(request: AddToCartRequest):
    try:
        # Try Storefront cart first
        result = await shopify.create_cart(request.variant_id, request.quantity)

        if "error" not in result:
            cart_data = result.get("data", {}).get("cartCreate", {})
            cart = cart_data.get("cart", {})
            if cart.get("checkoutUrl"):
                return JSONResponse(content={
                    "success": True,
                    "cart_id": cart.get("id"),
                    "checkout_url": cart.get("checkoutUrl"),
                    "message": "Product cart mein add ho gaya! Checkout karein.",
                    "action": "checkout"
                })

        # Fallback: Direct Shopify cart URL
        variant_id = request.variant_id
        if variant_id.startswith("gid://"):
            variant_id = variant_id.split("/")[-1]

        # Find product handle
        handle = ""
        for p in MOCK_PRODUCTS:
            if p["variant_id"] == request.variant_id or p["numeric_variant_id"] == variant_id:
                handle = p["handle"]
                break

        # Direct cart add URL (works on all Shopify stores!)
        cart_url = f"https://{SHOPIFY_SHOP_DOMAIN}/cart/add?id={variant_id}&quantity={request.quantity}"

        # Alternative: Product page
        product_url = f"https://{SHOPIFY_SHOP_DOMAIN}/products/{handle}" if handle else cart_url

        return JSONResponse(content={
            "success": True,
            "checkout_url": cart_url,
            "product_url": product_url,
            "message": "✅ Product cart mein add ho gaya! Neeche diye gaye button se checkout karein.",
            "action": "cart"
        })

    except Exception as e:
        print("Cart error:", str(e))
        return JSONResponse(
            status_code=500,
            content={"success": False, "message": "Cart add failed", "error": str(e)}
        )

# ====== SIMPLE CHAT ======
@app.post("/api/chat-simple")
async def chat_simple(request: SimpleChatRequest):
    try:
        messages = [{"role": "user", "content": request.message}]

        # Detect product intent
        product_keywords = ["product", "buy", "price", "dress", "shirt", "wallet", "kapra", "cheez",
                           "suit", "clothes", "fashion", "len", "lena", "purchase", "dikhao", "show",
                           "lawn", "fabric", "perfume", "gift", "box", "wear", "unstitched", "dikhayo"]
        needs_products = any(kw in request.message.lower() for kw in product_keywords)

        products = []
        if needs_products:
            try:
                products = await shopify.fetch_products(limit=6)
            except Exception as e:
                print("Product fetch error:", e)
                products = MOCK_PRODUCTS[:6]

        ai_response = await ai_service.chat_with_products(messages, products, force_products=needs_products and len(products) > 0)

        tool_calls = ai_response.get("tool_calls")
        if (tool_calls and len(tool_calls) > 0) or needs_products:
            if len(products) == 0:
                products = MOCK_PRODUCTS[:6]

            return JSONResponse(content={
                "success": True,
                "response": ai_response.get("text") or "Yeh hain hamare best products!",
                "product_cards": products,
                "quick_replies": ["Fabrics dekhein", "Wallets explore karein", "Perfumes check karein", "Discount code chahiye"],
                "session_id": request.session_id
            })

        return JSONResponse(content={
            "success": True,
            "response": ai_response.get("text") or "Main aapki madad karne ke liye tayyar hoon!",
            "product_cards": None,
            "quick_replies": ["Products dekhein", "Styling tips chahiye", "Discount code"],
            "session_id": request.session_id
        })

    except Exception as e:
        print("Chat error:", str(e))
        import traceback
        traceback.print_exc()
        return JSONResponse(
            status_code=500,
            content={"success": False, "response": "Kuch galat ho gaya. Dobara try karein.", "error": str(e)}
        )

# ====== FULL CHAT ======
@app.post("/api/chat")
async def chat_endpoint(request: ChatRequest):
    try:
        messages_dicts = []
        for msg in request.messages:
            messages_dicts.append({"role": msg.role, "content": msg.content})

        product_keywords = ["product", "buy", "price", "dress", "shirt", "wallet", "kapra", "cheez",
                           "suit", "clothes", "fashion", "len", "lena", "purchase", "dikhao", "show",
                           "lawn", "fabric", "perfume", "gift", "box", "wear", "unstitched", "dikhayo"]
        needs_products = any(kw in request.messages[-1].content.lower() for kw in product_keywords)

        products = []
        if needs_products:
            try:
                products = await shopify.fetch_products(limit=6)
            except Exception as e:
                print("Product fetch error:", e)
                products = MOCK_PRODUCTS[:6]

        ai_response = await ai_service.chat_with_products(messages_dicts, products, force_products=needs_products and len(products) > 0)

        tool_calls = ai_response.get("tool_calls")
        if (tool_calls and len(tool_calls) > 0) or needs_products:
            if len(products) == 0:
                products = MOCK_PRODUCTS[:6]

            return JSONResponse(content={
                "success": True,
                "response": ai_response.get("text") or "Yeh hain hamare best products!",
                "product_cards": products,
                "quick_replies": ["Fabrics dekhein", "Wallets explore karein", "Perfumes check karein", "Discount code chahiye"],
                "session_id": request.session_id
            })

        return JSONResponse(content={
            "success": True,
            "response": ai_response.get("text") or "Main aapki madad karne ke liye tayyar hoon!",
            "product_cards": None,
            "quick_replies": ["Products dekhein", "Styling tips chahiye", "Discount code"],
            "session_id": request.session_id
        })

    except Exception as e:
        print("Chat error:", str(e))
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/discount/generate")
async def generate_discount(request: DiscountRequest):
    try:
        # Simple mock discount for now
        code = f"REZON{uuid.uuid4().hex[:4].upper()}"
        return {
            "success": True,
            "discount": {
                "code": code,
                "percentage": request.percentage,
                "expires_at": (datetime.utcnow() + timedelta(days=7)).isoformat()
            },
            "message": f"Aap ke liye {request.percentage}% discount code: {code}"
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/vton/process")
async def process_vton(request: VTONRequest):
    return {"success": True, "status": "processing", "message": "VTON processing started"}

@app.post("/api/upload/image")
async def upload_image(file: UploadFile = File(...)):
    try:
        contents = await file.read()
        file_id = f"{uuid.uuid4()}_{file.filename}"
        upload_dir = "uploads"
        os.makedirs(upload_dir, exist_ok=True)
        file_path = os.path.join(upload_dir, file_id)

        with open(file_path, "wb") as f:
            f.write(contents)

        return {
            "success": True,
            "url": f"/uploads/{file_id}",
            "file_id": file_id
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", 8080))
    uvicorn.run(app, host="0.0.0.0", port=port)
