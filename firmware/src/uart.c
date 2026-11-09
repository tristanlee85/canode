#include "uart.h"

#include "board.h"
#include "stm32g0xx_hal.h"

#define RX_SIZE 256u    /* powers of two */
#define TX_SIZE 4096u

static volatile uint8_t  s_rx[RX_SIZE];
static volatile uint32_t s_rx_head, s_rx_tail;
static volatile uint8_t  s_tx[TX_SIZE];
static volatile uint32_t s_tx_head, s_tx_tail;
static volatile uint32_t s_tx_dropped;

void uart_init(void)
{
    __HAL_RCC_GPIOA_CLK_ENABLE();
    __HAL_RCC_USART2_CLK_ENABLE();

    GPIO_InitTypeDef gpio = {0};
    gpio.Pin = BOARD_UART_TX_PIN | BOARD_UART_RX_PIN;
    gpio.Mode = GPIO_MODE_AF_PP;
    gpio.Pull = GPIO_PULLUP;   /* idle-high RX if nothing is plugged into J4 */
    gpio.Speed = GPIO_SPEED_FREQ_LOW;
    gpio.Alternate = BOARD_UART_AF;
    HAL_GPIO_Init(BOARD_UART_PORT, &gpio);

    /* USART2 kernel clock = PCLK1 = 64 MHz (selected in system_clock_init).
     * 64 MHz / 115200 = 555.6 -> 556, 0.08 % error. */
    USART2->CR1 = 0;
    USART2->BRR = (HAL_RCC_GetPCLK1Freq() + BOARD_UART_BAUD / 2u) / BOARD_UART_BAUD;
    USART2->CR2 = 0;
    USART2->CR3 = 0;
    USART2->CR1 = USART_CR1_TE | USART_CR1_RE | USART_CR1_RXNEIE_RXFNEIE | USART_CR1_UE;

    /* Lower priority than FDCAN (0) and USB (1): console text can wait. */
    NVIC_SetPriority(USART2_LPUART2_IRQn, 2);
    NVIC_EnableIRQ(USART2_LPUART2_IRQn);
}

void USART2_LPUART2_IRQHandler(void)
{
    uint32_t isr = USART2->ISR;

    if (isr & (USART_ISR_ORE | USART_ISR_FE | USART_ISR_NE | USART_ISR_PE))
        USART2->ICR = USART_ICR_ORECF | USART_ICR_FECF | USART_ICR_NECF | USART_ICR_PECF;

    if (isr & USART_ISR_RXNE_RXFNE) {
        uint8_t c = (uint8_t)USART2->RDR;
        if (s_rx_head - s_rx_tail < RX_SIZE) {
            s_rx[s_rx_head & (RX_SIZE - 1u)] = c;
            s_rx_head++;
        }
    }

    if ((USART2->CR1 & USART_CR1_TXEIE_TXFNFIE) && (isr & USART_ISR_TXE_TXFNF)) {
        if (s_tx_tail != s_tx_head) {
            USART2->TDR = s_tx[s_tx_tail & (TX_SIZE - 1u)];
            s_tx_tail++;
        } else {
            USART2->CR1 &= ~USART_CR1_TXEIE_TXFNFIE;
        }
    }
}

int uart_getc(void)
{
    if (s_rx_tail == s_rx_head)
        return -1;
    int c = s_rx[s_rx_tail & (RX_SIZE - 1u)];
    s_rx_tail++;
    return c;
}

size_t uart_write(const char *s, size_t n)
{
    size_t i = 0;
    for (; i < n; i++) {
        if (s_tx_head - s_tx_tail >= TX_SIZE) {
            s_tx_dropped += (uint32_t)(n - i);
            break;
        }
        s_tx[s_tx_head & (TX_SIZE - 1u)] = (uint8_t)s[i];
        s_tx_head++;
    }
    /* Read-modify-write of CR1 races with the ISR clearing TXEIE: mask briefly. */
    __disable_irq();
    USART2->CR1 |= USART_CR1_TXEIE_TXFNFIE;
    __enable_irq();
    return i;
}

uint32_t uart_dropped(void)
{
    return s_tx_dropped;
}
